import logging
from sentinel.logger import configure_logger
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import numpy as np
import redis
from fastapi import FastAPI, HTTPException, Response, status
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel
from redis import Redis

from sentinel.serving.inference_client import TritonInferenceClient


DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379

DEFAULT_OTEL_ENDPOINT = "http://jaeger:4318/v1/traces"
OTEL_SERVICE_NAME = "sentinel-api"

FEATURE_SHAPE = (1, 1, 28, 28)
FEATURE_DTYPE = np.float32

MODEL_V1_NAME = "sentinel-mnist_1"
MODEL_V2_NAME = "sentinel-mnist_2"

logger = configure_logger("sentinel.api")


resource = Resource.create(
    {
        "service.name": OTEL_SERVICE_NAME,
    }
)

tracer_provider = TracerProvider(
    resource=resource,
)

otlp_exporter = OTLPSpanExporter(
    endpoint=os.getenv(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        DEFAULT_OTEL_ENDPOINT,
    )
)

tracer_provider.add_span_processor(
    BatchSpanProcessor(
        otlp_exporter,
    )
)

trace.set_tracer_provider(
    tracer_provider
)

tracer = trace.get_tracer(
    __name__
)


INFERENCE_REQUESTS = Counter(
    "inference_requests_total",
    "Total number of inference requests.",
    [
        "model",
        "status",
    ],
)

INFERENCE_LATENCY = Histogram(
    "inference_latency_seconds",
    "Inference processing latency in seconds.",
    [
        "model",
    ],
)


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
    inference_client_v1: TritonInferenceClient | None = None
    inference_client_v2: TritonInferenceClient | None = None


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


def create_inference_client(
    model_name: str,
) -> TritonInferenceClient:
    """Create and verify a Triton inference client."""

    client = TritonInferenceClient(
        model_name=model_name,
    )

    if not client.is_ready():
        client.close()

        raise RuntimeError(
            f"Triton model '{model_name}' is not ready."
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


def run_shadow_inference(
    feature_array: np.ndarray,
) -> None:
    """Run V2 shadow inference without affecting the user response."""

    with tracer.start_as_current_span(
        "v2_shadow_inference"
    ) as span:
        span.set_attribute(
            "ml.model.version",
            "v2",
        )

        inference_client_v2 = (
            application_state.inference_client_v2
        )

        if inference_client_v2 is None:
            INFERENCE_REQUESTS.labels(
                model="v2",
                status="unavailable",
            ).inc()

            span.set_status(
                Status(
                    StatusCode.ERROR,
                    "V2 inference client unavailable",
                )
            )

            logger.error(
                "shadow_model=v2 status=unavailable"
            )

            return

        start_time = time.perf_counter()

        try:
            prediction_result = (
                inference_client_v2.predict(
                    feature_array
                )
            )

        except (
            RuntimeError,
            ValueError,
        ) as error:
            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            INFERENCE_LATENCY.labels(
                model="v2",
            ).observe(
                elapsed_seconds
            )

            INFERENCE_REQUESTS.labels(
                model="v2",
                status="error",
            ).inc()

            span.record_exception(
                error
            )

            span.set_status(
                Status(
                    StatusCode.ERROR,
                    str(error),
                )
            )

            span.set_attribute(
                "inference.latency_ms",
                elapsed_seconds * 1000,
            )

            logger.error(
                "shadow_model=v2 status=error "
                "latency_ms=%.3f error=%s",
                elapsed_seconds * 1000,
                error,
            )

            return

        elapsed_seconds = (
            time.perf_counter()
            - start_time
        )

        INFERENCE_LATENCY.labels(
            model="v2",
        ).observe(
            elapsed_seconds
        )

        INFERENCE_REQUESTS.labels(
            model="v2",
            status="success",
        ).inc()

        span.set_attribute(
            "inference.latency_ms",
            elapsed_seconds * 1000,
        )

        span.set_attribute(
            "inference.predicted_class",
            prediction_result.predicted_class,
        )

        span.set_attribute(
            "inference.confidence",
            prediction_result.confidence,
        )

        span.set_status(
            Status(
                StatusCode.OK
            )
        )

        logger.info(
            (
                "shadow_model=v2 status=success "
                "latency_ms=%.3f predicted_class=%d "
                "confidence=%.6f"
            ),
            elapsed_seconds * 1000,
            prediction_result.predicted_class,
            prediction_result.confidence,
        )


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """Initialize and close shared application resources."""

    del app

    application_state.redis_client = create_redis_client()

    application_state.inference_client_v1 = (
        create_inference_client(
            model_name=MODEL_V1_NAME,
        )
    )

    application_state.inference_client_v2 = (
        create_inference_client(
            model_name=MODEL_V2_NAME,
        )
    )

    yield

    if application_state.redis_client is not None:
        application_state.redis_client.close()

    if application_state.inference_client_v1 is not None:
        application_state.inference_client_v1.close()

    if application_state.inference_client_v2 is not None:
        application_state.inference_client_v2.close()

    tracer_provider.shutdown()


app = FastAPI(
    title="Sentinel Serving API",
    description=(
        "Thin real-time MNIST API with "
        "V1 production inference and V2 shadow inference."
    ),
    version="2.4.0",
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
    inference_client_v1 = application_state.inference_client_v1
    inference_client_v2 = application_state.inference_client_v2

    if (
        redis_client is None
        or inference_client_v1 is None
        or inference_client_v2 is None
    ):
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

    if not inference_client_v1.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Triton model V1 is unavailable.",
        )

    if not inference_client_v2.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Triton model V2 is unavailable.",
        )

    return {"status": "healthy"}


@app.get("/metrics")
def metrics() -> Response:
    """Expose Prometheus metrics."""

    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post(
    "/predict/{image_id}",
    response_model=PredictionResponse,
)
def predict(
    image_id: str,
) -> PredictionResponse:
    """Run V1 inference and mirror the request to V2."""

    with tracer.start_as_current_span(
        "predict_request"
    ) as request_span:
        request_span.set_attribute(
            "sentinel.image_id",
            image_id,
        )

        redis_client = application_state.redis_client
        inference_client_v1 = (
            application_state.inference_client_v1
        )

        if (
            redis_client is None
            or inference_client_v1 is None
        ):
            request_span.set_status(
                Status(
                    StatusCode.ERROR,
                    "API dependencies not initialized",
                )
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_503_SERVICE_UNAVAILABLE
                ),
                detail=(
                    "API dependencies are not initialized."
                ),
            )

        redis_key = f"feat:{image_id}"

        with tracer.start_as_current_span(
            "redis_lookup"
        ) as redis_span:
            redis_span.set_attribute(
                "db.system",
                "redis",
            )

            redis_span.set_attribute(
                "redis.key",
                redis_key,
            )

            try:
                feature_bytes = redis_client.get(
                    redis_key
                )

            except redis.RedisError as error:
                redis_span.record_exception(
                    error
                )

                redis_span.set_status(
                    Status(
                        StatusCode.ERROR,
                        str(error),
                    )
                )

                raise HTTPException(
                    status_code=(
                        status.HTTP_503_SERVICE_UNAVAILABLE
                    ),
                    detail="Redis is unavailable.",
                ) from error

            redis_span.set_status(
                Status(
                    StatusCode.OK
                )
            )

        if feature_bytes is None:
            request_span.set_status(
                Status(
                    StatusCode.ERROR,
                    "Feature not found",
                )
            )

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not processed yet",
            )

        if not isinstance(
            feature_bytes,
            bytes,
        ):
            request_span.set_status(
                Status(
                    StatusCode.ERROR,
                    "Invalid Redis feature format",
                )
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=(
                    "Stored feature has an invalid format."
                ),
            )

        try:
            feature_array = deserialize_feature(
                feature_bytes
            )

        except ValueError as error:
            request_span.record_exception(
                error
            )

            request_span.set_status(
                Status(
                    StatusCode.ERROR,
                    str(error),
                )
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=(
                    "Stored feature has an invalid shape."
                ),
            ) from error

        with tracer.start_as_current_span(
            "v1_model_inference"
        ) as inference_span:
            inference_span.set_attribute(
                "ml.model.version",
                "v1",
            )

            start_time = time.perf_counter()

            try:
                prediction_result_v1 = (
                    inference_client_v1.predict(
                        feature_array
                    )
                )

            except RuntimeError as error:
                elapsed_seconds = (
                    time.perf_counter()
                    - start_time
                )

                INFERENCE_LATENCY.labels(
                    model="v1",
                ).observe(
                    elapsed_seconds
                )

                INFERENCE_REQUESTS.labels(
                    model="v1",
                    status="error",
                ).inc()

                inference_span.record_exception(
                    error
                )

                inference_span.set_attribute(
                    "inference.latency_ms",
                    elapsed_seconds * 1000,
                )

                inference_span.set_status(
                    Status(
                        StatusCode.ERROR,
                        str(error),
                    )
                )

                raise HTTPException(
                    status_code=(
                        status.HTTP_503_SERVICE_UNAVAILABLE
                    ),
                    detail=(
                        "Primary inference service failed."
                    ),
                ) from error

            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            INFERENCE_LATENCY.labels(
                model="v1",
            ).observe(
                elapsed_seconds
            )

            INFERENCE_REQUESTS.labels(
                model="v1",
                status="success",
            ).inc()

            inference_span.set_attribute(
                "inference.latency_ms",
                elapsed_seconds * 1000,
            )

            inference_span.set_attribute(
                "inference.predicted_class",
                prediction_result_v1.predicted_class,
            )

            inference_span.set_attribute(
                "inference.confidence",
                prediction_result_v1.confidence,
            )

            inference_span.set_status(
                Status(
                    StatusCode.OK
                )
            )

            logger.info(
                "Prediction completed",
                extra={
                    "structured_data": {
                        "image_id": image_id,
                        "model": "v1",
                        "predicted_class": (
                            prediction_result_v1.predicted_class
                        ),
                        "confidence": (
                            prediction_result_v1.confidence
                        ),
                        "latency_seconds": (
                            elapsed_seconds
                        ),
                    }
                },
            )

        run_shadow_inference(
            feature_array=feature_array,
        )

        predicted_class = (
            prediction_result_v1.predicted_class
        )

        predicted_label = CLASS_NAMES.get(
            predicted_class
        )

        if predicted_label is None:
            request_span.set_status(
                Status(
                    StatusCode.ERROR,
                    "Unknown predicted class",
                )
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_500_INTERNAL_SERVER_ERROR
                ),
                detail=(
                    "Inference returned an unknown class."
                ),
            )

        request_span.set_attribute(
            "inference.predicted_class",
            predicted_class,
        )

        request_span.set_status(
            Status(
                StatusCode.OK
            )
        )

        return PredictionResponse(
            image_id=image_id,
            predicted_class=predicted_class,
            predicted_label=predicted_label,
            confidence=prediction_result_v1.confidence,
            model_version="v1",
        )