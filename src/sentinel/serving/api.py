import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import numpy as np
import redis
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from redis import Redis

from sentinel.serving.inference_client import TritonInferenceClient


DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379

FEATURE_SHAPE = (1, 1, 28, 28)
FEATURE_DTYPE = np.float32

CLASS_NAMES = {
    0: "0",
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
    6: "6",
    7: "7",
    8: "8",
    9: "9",
}


class PredictionResponse(BaseModel):
    """Represent a successful model prediction."""

    image_id: str
    predicted_class: int
    predicted_label: str
    confidence: float
    model_version: str


class ApplicationState:
    """Store shared application resources."""

    redis_client: Redis | None = None
    inference_client: TritonInferenceClient | None = None


application_state = ApplicationState()


def create_redis_client() -> Redis:
    """Create and verify a Redis connection."""

    client = redis.Redis(
        host=os.getenv(
            "REDIS_HOST",
            DEFAULT_REDIS_HOST,
        ),
        port=int(
            os.getenv(
                "REDIS_PORT",
                str(DEFAULT_REDIS_PORT),
            )
        ),
        decode_responses=False,
    )

    client.ping()

    return client


def create_inference_client() -> TritonInferenceClient:
    """Create and verify the Triton inference client."""

    client = TritonInferenceClient()

    if not client.is_ready():
        client.close()

        raise RuntimeError(
            "Triton or the configured model is not ready."
        )

    return client


def deserialize_feature(
    feature_bytes: bytes,
) -> np.ndarray:
    """Convert Redis feature bytes into a NumPy array."""

    feature_array = np.frombuffer(
        feature_bytes,
        dtype=FEATURE_DTYPE,
    )

    expected_size = int(
        np.prod(FEATURE_SHAPE)
    )

    if feature_array.size != expected_size:
        raise ValueError(
            f"Expected {expected_size} feature values, "
            f"received {feature_array.size}."
        )

    return feature_array.reshape(
        FEATURE_SHAPE
    ).copy()


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """Initialize and close shared application resources."""

    del app

    application_state.redis_client = create_redis_client()
    application_state.inference_client = create_inference_client()

    yield

    if application_state.redis_client is not None:
        application_state.redis_client.close()

    if application_state.inference_client is not None:
        application_state.inference_client.close()


app = FastAPI(
    title="Sentinel Serving API",
    description=(
        "Thin real-time MNIST API backed by "
        "ClearML Serving and Triton."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/live")
def live() -> dict[str, str]:
    """Return the process liveness status."""

    return {"status": "alive"}


@app.get("/health")
def health() -> dict[str, str]:
    """Return the readiness status of API dependencies."""

    redis_client = application_state.redis_client
    inference_client = application_state.inference_client

    if redis_client is None or inference_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API dependencies are not initialized.",
        )

    try:
        redis_client.ping()
    except redis.RedisError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable.",
        ) from error

    if not inference_client.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Triton inference service is unavailable.",
        )

    return {"status": "healthy"}


@app.post(
    "/predict/{image_id}",
    response_model=PredictionResponse,
)
def predict(
    image_id: str,
) -> PredictionResponse:
    """Predict an MNIST class using ClearML Serving and Triton."""

    redis_client = application_state.redis_client
    inference_client = application_state.inference_client

    if redis_client is None or inference_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API dependencies are not initialized.",
        )

    redis_key = f"feat:{image_id}"

    try:
        feature_bytes = redis_client.get(redis_key)
    except redis.RedisError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable.",
        ) from error

    if feature_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not processed yet",
        )

    if not isinstance(feature_bytes, bytes):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored feature has an invalid format.",
        )

    try:
        feature_array = deserialize_feature(feature_bytes)
        prediction_result = inference_client.predict(
            feature_array
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored feature has an invalid shape.",
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inference service failed.",
        ) from error

    predicted_class = prediction_result.predicted_class

    predicted_label = CLASS_NAMES.get(
        predicted_class
    )

    if predicted_label is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Inference returned an unknown class.",
        )

    return PredictionResponse(
        image_id=image_id,
        predicted_class=predicted_class,
        predicted_label=predicted_label,
        confidence=prediction_result.confidence,
        model_version="v1-triton",
    )