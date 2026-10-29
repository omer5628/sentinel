
"""Storage operations for the Sentinel ingestion Worker."""

import json
import os

import psycopg2
import redis
import torch
from psycopg2.extensions import connection as PostgreSQLConnection
from redis import Redis

from sentinel.consumers.worker_config import WorkerConfig


_DEFAULT_CONFIG = WorkerConfig()

# Preserve existing constants for backward compatibility.
FEATURE_TTL_SECONDS = _DEFAULT_CONFIG.feature_ttl_seconds
MODEL_VERSION = "v1"

DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379

DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DATABASE = "sentinel"
DEFAULT_POSTGRES_USERNAME = "sentinel"
DEFAULT_POSTGRES_PASSWORD = "sentinel"


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


def create_postgres_connection() -> PostgreSQLConnection:
    """Create a PostgreSQL connection."""

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


class PostgresWriter:
    """Maintain a reusable PostgreSQL connection with reconnection support."""

    def __init__(self) -> None:
        self.connection: PostgreSQLConnection | None = None

    def ensure_connection(self) -> PostgreSQLConnection:
        """Return an active connection, reconnecting when necessary."""

        if self.connection is None or self.connection.closed:
            self.connection = create_postgres_connection()

        return self.connection

    def write(
        self,
        event_id: str,
        image_id: str,
        raw_image: bytes,
        tensor: torch.Tensor,
    ) -> None:
        """Append one feature event to PostgreSQL."""

        connection = self.ensure_connection()
        vector_json = tensor_to_json(tensor)

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO feature_log (
                        event_id,
                        image_id,
                        raw_image,
                        vector,
                        model_version
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s)
                    """,
                    (
                        event_id,
                        image_id,
                        psycopg2.Binary(raw_image),
                        vector_json,
                        MODEL_VERSION,
                    ),
                )

            connection.commit()

        except psycopg2.Error:
            self._discard_connection()
            raise

    def _discard_connection(self) -> None:
        """Close and discard a failed PostgreSQL connection."""

        if self.connection is not None:
            try:
                self.connection.rollback()
            except psycopg2.Error:
                pass

            try:
                self.connection.close()
            except psycopg2.Error:
                pass

        self.connection = None

    def close(self) -> None:
        """Close the active PostgreSQL connection."""

        if self.connection is not None and not self.connection.closed:
            self.connection.close()

        self.connection = None


def tensor_to_json(tensor: torch.Tensor) -> str:
    """Serialize a tensor as JSON for PostgreSQL storage."""

    return json.dumps(tensor.detach().cpu().tolist())


def write_to_redis(
    redis_client: Redis,
    image_id: str,
    tensor: torch.Tensor,
    config: WorkerConfig | None = None,
) -> None:
    """Write the latest feature tensor to Redis."""

    settings = config if config is not None else _DEFAULT_CONFIG

    redis_key = f"feat:{image_id}"

    redis_client.setex(
        name=redis_key,
        time=settings.feature_ttl_seconds,
        value=tensor.detach().cpu().numpy().tobytes(),
    )
