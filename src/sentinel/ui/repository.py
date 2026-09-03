import os
from typing import Any
from uuid import UUID

import psycopg2
from psycopg2.extensions import connection as PostgreSQLConnection
from psycopg2.extras import RealDictCursor


DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DATABASE = "sentinel"
DEFAULT_POSTGRES_USERNAME = "sentinel"
DEFAULT_POSTGRES_PASSWORD = "sentinel"


def create_postgres_connection() -> PostgreSQLConnection:
    """Create a connection to the offline feature store."""

    return psycopg2.connect(
        host=os.getenv(
            "POSTGRES_HOST",
            DEFAULT_POSTGRES_HOST,
        ),
        port=int(
            os.getenv(
                "POSTGRES_PORT",
                str(DEFAULT_POSTGRES_PORT),
            )
        ),
        dbname=os.getenv(
            "POSTGRES_DB",
            DEFAULT_POSTGRES_DATABASE,
        ),
        user=os.getenv(
            "POSTGRES_USER",
            DEFAULT_POSTGRES_USERNAME,
        ),
        password=os.getenv(
            "POSTGRES_PASSWORD",
            DEFAULT_POSTGRES_PASSWORD,
        ),
    )


def fetch_recent_events(
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return the most recently processed feature events."""

    with create_postgres_connection() as connection:
        with connection.cursor(
            cursor_factory=RealDictCursor,
        ) as cursor:
            cursor.execute(
                """
                SELECT
                    event_id,
                    image_id,
                    timestamp,
                    model_version,
                    label
                FROM feature_log
                ORDER BY timestamp DESC
                LIMIT %s
                """,
                (limit,),
            )

            rows = cursor.fetchall()

    return [dict(row) for row in rows]


def fetch_event_image(
    event_id: UUID,
) -> bytes | None:
    """Return the stored raw image for one event."""

    with create_postgres_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT raw_image
                FROM feature_log
                WHERE event_id = %s
                """,
                (str(event_id),),
            )

            row = cursor.fetchone()

    if row is None or row[0] is None:
        return None

    return bytes(row[0])