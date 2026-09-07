from datetime import datetime
from uuid import UUID

import psycopg2
from fastapi import FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel

from sentinel.ui.monitoring import fetch_rabbitmq_status
from sentinel.ui.repository import (
    check_postgres_connection,
    fetch_event_image,
    fetch_recent_events,
    has_recent_mnist_event,
)

from sentinel.ui.producer_controller import (
    get_producer_pid,
    is_producer_running,
    start_producer,
    stop_producer,
)


class EventResponse(BaseModel):
    """Represent one image processed by the Sentinel Worker."""

    event_id: UUID
    image_id: str
    timestamp: datetime
    model_version: str
    inference_model_version: str | None
    predicted_class: int | None
    confidence: float | None
    label: str | None
    status: str = "processed"


class SystemStatusResponse(BaseModel):
    """Represent the current Sentinel pipeline status."""

    system: str
    producer: str
    rabbitmq: str
    worker: str
    feature_store: str
    queue_depth: int
    worker_consumers: int

class ProducerControlResponse(BaseModel):
    """Represent the managed Producer process state."""

    running: bool
    pid: int | None

app = FastAPI(
    title="Sentinel UI API",
    description="Backend API for the Sentinel operations frontend.",
    version="1.0.0",
)


@app.get("/live")
def live() -> dict[str, str]:
    """Return the UI API process liveness status."""

    return {"status": "alive"}


@app.get(
    "/status",
    response_model=SystemStatusResponse,
)
def get_system_status() -> SystemStatusResponse:
    """Return the current Sentinel pipeline status."""

    postgres_online = False
    producer_status = "unknown"

    try:
        postgres_online = check_postgres_connection()

        producer_active = has_recent_mnist_event(
            window_seconds=10,
        )

        producer_status = (
            "active"
            if producer_active
            else "idle"
        )

    except psycopg2.Error:
        postgres_online = False

    (
        rabbitmq_online,
        worker_consumers,
        queue_depth,
    ) = fetch_rabbitmq_status()

    worker_online = (
        rabbitmq_online
        and worker_consumers > 0
    )

    system_online = (
        postgres_online
        and rabbitmq_online
        and worker_online
    )

    return SystemStatusResponse(
        system=(
            "online"
            if system_online
            else "degraded"
        ),
        producer=producer_status,
        rabbitmq=(
            "online"
            if rabbitmq_online
            else "offline"
        ),
        worker=(
            "online"
            if worker_online
            else "offline"
        ),
        feature_store=(
            "online"
            if postgres_online
            else "offline"
        ),
        queue_depth=queue_depth,
        worker_consumers=worker_consumers,
    )

@app.get(
    "/producer/status",
    response_model=ProducerControlResponse,
)
def get_managed_producer_status() -> ProducerControlResponse:
    """Return the managed Producer process state."""

    return ProducerControlResponse(
        running=is_producer_running(),
        pid=get_producer_pid(),
    )


@app.post(
    "/producer/start",
    response_model=ProducerControlResponse,
)
def start_managed_producer() -> ProducerControlResponse:
    """Start the managed Sentinel Producer."""

    try:
        pid = start_producer()
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return ProducerControlResponse(
        running=is_producer_running(),
        pid=pid,
    )


@app.post(
    "/producer/stop",
    response_model=ProducerControlResponse,
)
def stop_managed_producer() -> ProducerControlResponse:
    """Stop the managed Sentinel Producer."""

    stop_producer()

    return ProducerControlResponse(
        running=is_producer_running(),
        pid=get_producer_pid(),
    )


@app.get(
    "/events",
    response_model=list[EventResponse],
)
def get_events(
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
) -> list[EventResponse]:
    """Return the latest events processed by the Worker."""

    try:
        rows = fetch_recent_events(limit=limit)
    except psycopg2.Error as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from error

    return [
        EventResponse(
            event_id=row["event_id"],
            image_id=row["image_id"],
            timestamp=row["timestamp"],
            model_version=row["model_version"],
            inference_model_version=row["inference_model_version"],
            predicted_class=row["predicted_class"],
            confidence=row["confidence"],
            label=row["label"],
        )
        for row in rows
    ]


@app.get("/events/{event_id}/image")
def get_event_image(
    event_id: UUID,
) -> Response:
    """Return the raw PNG stored for one processed event."""

    try:
        image_bytes = fetch_event_image(event_id=event_id)
    except psycopg2.Error as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PostgreSQL is unavailable.",
        ) from error

    if image_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image was not found.",
        )

    return Response(
        content=image_bytes,
        media_type="image/png",
    )