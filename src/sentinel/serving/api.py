import argparse
import json
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Literal

import httpx
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
from pydantic import BaseModel, Field, ValidationError
from redis import Redis

from sentinel.logger import configure_logger


DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379

DEFAULT_CLEARML_CANARY_URL = (
    "http://clearml-serving-inference.default.svc.cluster.local:8080"
    "/serve/sentinel-mnist-canary"
)
DEFAULT_CLEARML_TIMEOUT_SECONDS = 5.0

DEFAULT_OTEL_ENDPOINT = "http://jaeger:4318/v1/traces"
OTEL_SERVICE_NAME = "sentinel-api"

FEATURE_SHAPE = (1, 1, 28, 28)
FEATURE_DTYPE = np.float32

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


class ClearMLPrediction(BaseModel):
    """Represent a prediction returned by ClearML Serving."""

    predicted_class: int = Field(
        ge=0,
        le=9,
    )

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    model_version: Literal[
        "v1",
        "v2",
    ]


class PredictionResponse(BaseModel):
    """Represent a successful Sentinel prediction."""

    image_id: str

    predicted_class: int = Field(
        ge=0,
        le=9,
    )

    predicted_label: str

    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )

    model_version: Literal[
        "v1",
        "v2",
    ]


class ApplicationState:
    """Store shared application resources."""

    redis_client: Redis | None = None
    clearml_client: httpx.Client | None = None


application_state = ApplicationState()


def get_clearml_canary_url() -> str:
    """Return the configured ClearML Canary endpoint."""

    return os.getenv(
        "CLEARML_CANARY_URL",
        DEFAULT_CLEARML_CANARY_URL,
    )


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


def create_clearml_client() -> httpx.Client:
    """Create a reusable ClearML Serving HTTP client."""

    timeout_seconds = float(
        os.getenv(
            "CLEARML_TIMEOUT_SECONDS",
            str(
                DEFAULT_CLEARML_TIMEOUT_SECONDS
            ),
        )
    )

    return httpx.Client(
        timeout=timeout_seconds,
    )


def deserialize_feature(
    feature_bytes: bytes,
) -> np.ndarray:
    """Convert Redis feature bytes into a NumPy array."""

    feature_array = np.frombuffer(
        feature_bytes,
        dtype=FEATURE_DTYPE,
    )

    expected_size = int(
        np.prod(
            FEATURE_SHAPE
        )
    )

    if feature_array.size != expected_size:
        raise ValueError(
            f"Expected {expected_size} feature values, "
            f"received {feature_array.size}."
        )

    return feature_array.reshape(
        FEATURE_SHAPE
    ).copy()


def run_canary_inference(
    feature_array: np.ndarray,
) -> ClearMLPrediction:
    """Send an inference request through the ClearML Canary endpoint."""

    clearml_client = (
        application_state.clearml_client
    )

    if clearml_client is None:
        raise RuntimeError(
            "ClearML Serving client is not initialized."
        )

    response = clearml_client.post(
        get_clearml_canary_url(),
        json={
            "pixels": feature_array.tolist(),
        },
    )

    response.raise_for_status()

    response_data = response.json()

    return ClearMLPrediction.model_validate(
        response_data
    )


@asynccontextmanager
async def lifespan(
    app: FastAPI,
) -> AsyncIterator[None]:
    """Initialize and close shared application resources."""

    del app

    application_state.redis_client = (
        create_redis_client()
    )

    application_state.clearml_client = (
        create_clearml_client()
    )

    yield

    if application_state.redis_client is not None:
        application_state.redis_client.close()

    if application_state.clearml_client is not None:
        application_state.clearml_client.close()

    tracer_provider.shutdown()


app = FastAPI(
    title="Sentinel Serving API",
    description=(
        "Thin real-time MNIST API using "
        "ClearML Serving Canary inference."
    ),
    version="2.5.0",
    lifespan=lifespan,
)


@app.get("/live")
def live() -> dict[str, str]:
    """Return the process liveness status."""

    return {
        "status": "alive",
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Return the readiness status of API dependencies."""

    redis_client = (
        application_state.redis_client
    )

    clearml_client = (
        application_state.clearml_client
    )

    if (
        redis_client is None
        or clearml_client is None
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "API dependencies are not initialized."
            ),
        )

    try:
        redis_client.ping()

    except redis.RedisError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail="Redis is unavailable.",
        ) from error

    return {
        "status": "healthy",
    }


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
    """Run inference through the ClearML Canary endpoint."""

    with tracer.start_as_current_span(
        "predict_request"
    ) as request_span:
        request_span.set_attribute(
            "sentinel.image_id",
            image_id,
        )

        redis_client = (
            application_state.redis_client
        )

        clearml_client = (
            application_state.clearml_client
        )

        if (
            redis_client is None
            or clearml_client is None
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
                feature_bytes = (
                    redis_client.get(
                        redis_key
                    )
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

            logger.error(
                "Prediction error",
                extra={
                    "structured_data": {
                        "event": "feature_not_found",
                        "image_id": image_id,
                        "status": "error",
                        "http_status": 404,
                    }
                },
            )

            raise HTTPException(
                status_code=(
                    status.HTTP_404_NOT_FOUND
                ),
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
            feature_array = (
                deserialize_feature(
                    feature_bytes
                )
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
            "clearml_canary_inference"
        ) as inference_span:
            inference_span.set_attribute(
                "clearml.endpoint",
                "sentinel-mnist-canary",
            )

            start_time = (
                time.perf_counter()
            )

            try:
                prediction_result = (
                    run_canary_inference(
                        feature_array
                    )
                )

            except (
                httpx.HTTPError,
                ValidationError,
                ValueError,
                RuntimeError,
            ) as error:
                elapsed_seconds = (
                    time.perf_counter()
                    - start_time
                )

                INFERENCE_LATENCY.labels(
                    model="canary",
                ).observe(
                    elapsed_seconds
                )

                INFERENCE_REQUESTS.labels(
                    model="canary",
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

                logger.error(
                    "Prediction error",
                    extra={
                        "structured_data": {
                            "event": (
                                "clearml_inference_failed"
                            ),
                            "image_id": image_id,
                            "status": "error",
                            "latency_seconds": (
                                elapsed_seconds
                            ),
                            "error": str(
                                error
                            ),
                        }
                    },
                )

                raise HTTPException(
                    status_code=(
                        status.HTTP_503_SERVICE_UNAVAILABLE
                    ),
                    detail=(
                        "ClearML Serving inference failed."
                    ),
                ) from error

            elapsed_seconds = (
                time.perf_counter()
                - start_time
            )

            model_version = (
                prediction_result.model_version
            )

            INFERENCE_LATENCY.labels(
                model=model_version,
            ).observe(
                elapsed_seconds
            )

            INFERENCE_REQUESTS.labels(
                model=model_version,
                status="success",
            ).inc()

            inference_span.set_attribute(
                "ml.model.version",
                model_version,
            )

            inference_span.set_attribute(
                "inference.latency_ms",
                elapsed_seconds * 1000,
            )

            inference_span.set_attribute(
                "inference.predicted_class",
                prediction_result.predicted_class,
            )

            inference_span.set_attribute(
                "inference.confidence",
                prediction_result.confidence,
            )

            inference_span.set_status(
                Status(
                    StatusCode.OK
                )
            )

        predicted_class = (
            prediction_result.predicted_class
        )

        predicted_label = (
            CLASS_NAMES.get(
                predicted_class
            )
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
            "ml.model.version",
            model_version,
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

        logger.info(
            "Prediction completed",
            extra={
                "structured_data": {
                    "image_id": image_id,
                    "model": model_version,
                    "predicted_class": (
                        predicted_class
                    ),
                    "confidence": (
                        prediction_result.confidence
                    ),
                    "latency_seconds": (
                        elapsed_seconds
                    ),
                }
            },
        )

        return PredictionResponse(
            image_id=image_id,
            predicted_class=predicted_class,
            predicted_label=predicted_label,
            confidence=(
                prediction_result.confidence
            ),
            model_version=model_version,
        )


def export_openapi() -> None:
    """Write the current FastAPI OpenAPI specification to stdout."""

    json.dump(
        app.openapi(),
        sys.stdout,
        indent=2,
    )

    sys.stdout.write("\n")


def main() -> None:
    """Handle command-line operations for the serving API."""

    parser = argparse.ArgumentParser(
        description=(
            "Sentinel Serving API utilities."
        )
    )

    parser.add_argument(
        "--export-openapi",
        action="store_true",
        help=(
            "Export the FastAPI OpenAPI "
            "specification as JSON."
        ),
    )

    args = parser.parse_args()

    if args.export_openapi:
        export_openapi()
        return

    parser.print_help()


if __name__ == "__main__":
    main()