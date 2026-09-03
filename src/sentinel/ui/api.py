from datetime import datetime
from uuid import UUID

import psycopg2
from fastapi import FastAPI, HTTPException, Query, Response, status
from pydantic import BaseModel

from sentinel.ui.repository import (
    fetch_event_image,
    fetch_recent_events,
)


class EventResponse(BaseModel):
    """Represent one image processed by the Sentinel Worker."""

    event_id: UUID
    image_id: str
    timestamp: datetime
    model_version: str
    label: str | None
    status: str = "processed"


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