
"""Configuration for Sentinel Worker operational settings."""

import os
from dataclasses import dataclass


def _read_string(name: str, default: str) -> str:
    """Read a required non-empty string setting."""

    value = os.getenv(name, default).strip()

    if not value:
        raise ValueError(
            f"Worker configuration '{name}' must not be empty."
        )

    return value


def _read_positive_int(name: str, default: int) -> int:
    """Read and validate a positive integer setting."""

    raw_value = os.getenv(name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"Worker configuration '{name}' must be an integer."
        ) from error

    if value <= 0:
        raise ValueError(
            f"Worker configuration '{name}' must be positive."
        )

    return value


@dataclass(frozen=True)
class WorkerConfig:
    """Operational settings for the ingestion Worker."""

    queue_name: str = "video_stream"

    dead_letter_exchange: str = "sentinel.dlx"
    dead_letter_queue: str = "video_stream.dlq"
    dead_letter_routing_key: str = "video_stream.invalid"

    feature_ttl_seconds: int = 3600
    prefetch_count: int = 1

    rabbitmq_heartbeat: int = 60
    rabbitmq_blocked_timeout: int = 30

    @classmethod
    def from_environment(cls) -> "WorkerConfig":
        """Load Worker settings from environment variables."""

        defaults = cls()

        return cls(
            queue_name=_read_string(
                "WORKER_QUEUE_NAME",
                defaults.queue_name,
            ),
            dead_letter_exchange=_read_string(
                "WORKER_DEAD_LETTER_EXCHANGE",
                defaults.dead_letter_exchange,
            ),
            dead_letter_queue=_read_string(
                "WORKER_DEAD_LETTER_QUEUE",
                defaults.dead_letter_queue,
            ),
            dead_letter_routing_key=_read_string(
                "WORKER_DEAD_LETTER_ROUTING_KEY",
                defaults.dead_letter_routing_key,
            ),
            feature_ttl_seconds=_read_positive_int(
                "WORKER_FEATURE_TTL_SECONDS",
                defaults.feature_ttl_seconds,
            ),
            prefetch_count=_read_positive_int(
                "WORKER_PREFETCH_COUNT",
                defaults.prefetch_count,
            ),
            rabbitmq_heartbeat=_read_positive_int(
                "WORKER_RABBITMQ_HEARTBEAT",
                defaults.rabbitmq_heartbeat,
            ),
            rabbitmq_blocked_timeout=_read_positive_int(
                "WORKER_RABBITMQ_BLOCKED_TIMEOUT",
                defaults.rabbitmq_blocked_timeout,
            ),
        )
