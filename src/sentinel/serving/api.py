import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import numpy as np
import redis
import torch
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from redis import Redis
from torch import Tensor
from torch.nn import Module


DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379
DEFAULT_MODEL_PATH = "artifacts/model.pt"

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
    model: Module | None = None


application_state = ApplicationState()


def create_redis_client() -> Redis:
    """Create and verify a Redis connection."""

    client = redis.Redis(
        host=os.getenv("REDIS_HOST", DEFAULT_REDIS_HOST),
        port=int(os.getenv("REDIS_PORT", str(DEFAULT_REDIS_PORT))),
        decode_responses=False,
    )

    client.ping()
    return client


def load_model() -> Module:
    """Load the TorchScript model used for inference."""

    model_path = Path(
        os.getenv(
            "MODEL_PATH",
            DEFAULT_MODEL_PATH,
        )
    )

    if not model_path.is_file():
        raise FileNotFoundError(f"Model file was not found: {model_path}")

    model = torch.jit.load(
        str(model_path),
        map_location="cpu",
    )
    model.eval()

    return model


def deserialize_feature(feature_bytes: bytes) -> Tensor:
    """Convert Redis feature bytes into a PyTorch tensor."""

    feature_array = np.frombuffer(
        feature_bytes,
        dtype=FEATURE_DTYPE,
    )

    expected_size = int(np.prod(FEATURE_SHAPE))

    if feature_array.size != expected_size:
        raise ValueError(
            f"Expected {expected_size} feature values, received {feature_array.size}."
        )

    reshaped_array = feature_array.reshape(FEATURE_SHAPE).copy()

    return torch.from_numpy(reshaped_array)


def get_prediction(
    model: Module,
    feature_tensor: Tensor,
) -> tuple[int, float]:
    """Run model inference and return the predicted class and confidence."""

    with torch.inference_mode():
        logits = model(feature_tensor)
        probabilities = torch.softmax(logits, dim=1)

        predicted_class = int(
            torch.argmax(
                probabilities,
                dim=1,
            ).item()
        )
        confidence = float(probabilities[0, predicted_class].item())

    return predicted_class, confidence


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and close shared application resources."""

    del app

    application_state.redis_client = create_redis_client()
    application_state.model = load_model()

    yield

    if application_state.redis_client is not None:
        application_state.redis_client.close()


app = FastAPI(
    title="Sentinel Serving API",
    description="Real-time MNIST prediction API.",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    """Return the health status of the API."""

    redis_client = application_state.redis_client
    model = application_state.model

    if redis_client is None or model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API dependencies are not ready.",
        )

    try:
        redis_client.ping()
    except redis.RedisError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis is unavailable.",
        ) from error

    return {"status": "healthy"}


@app.post(
    "/predict/{image_id}",
    response_model=PredictionResponse,
)
def predict(image_id: str) -> PredictionResponse:
    """Predict the MNIST class for a processed image."""

    redis_client = application_state.redis_client
    model = application_state.model

    if redis_client is None or model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API dependencies are not ready.",
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
        feature_tensor = deserialize_feature(feature_bytes)
        predicted_class, confidence = get_prediction(
            model=model,
            feature_tensor=feature_tensor,
        )
    except (ValueError, RuntimeError) as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prediction failed.",
        ) from error

    return PredictionResponse(
        image_id=image_id,
        predicted_class=predicted_class,
        predicted_label=CLASS_NAMES[predicted_class],
        confidence=confidence,
        model_version="v1",
    )
