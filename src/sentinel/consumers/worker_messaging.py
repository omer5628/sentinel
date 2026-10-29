
"""RabbitMQ infrastructure for the Sentinel ingestion Worker."""

import logging
import os

import pika
from pika.adapters.blocking_connection import BlockingChannel

from sentinel.consumers.worker_config import WorkerConfig


_DEFAULT_CONFIG = WorkerConfig()

# Preserve existing imports for backward compatibility.
QUEUE_NAME = _DEFAULT_CONFIG.queue_name

DEAD_LETTER_EXCHANGE = _DEFAULT_CONFIG.dead_letter_exchange
DEAD_LETTER_QUEUE = _DEFAULT_CONFIG.dead_letter_queue
DEAD_LETTER_ROUTING_KEY = _DEFAULT_CONFIG.dead_letter_routing_key

DEFAULT_RABBITMQ_HOST = "localhost"
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_RABBITMQ_USERNAME = "sentinel"
DEFAULT_RABBITMQ_PASSWORD = "sentinel"


logger = logging.getLogger(__name__)


def _resolve_config(config: WorkerConfig | None) -> WorkerConfig:
    """Use supplied settings or preserve the original defaults."""

    return config if config is not None else _DEFAULT_CONFIG


def create_rabbitmq_connection(
    config: WorkerConfig | None = None,
) -> pika.BlockingConnection:
    """Create a connection to RabbitMQ."""

    settings = _resolve_config(config)

    credentials = pika.PlainCredentials(
        username=os.getenv(
            "RABBITMQ_USERNAME",
            DEFAULT_RABBITMQ_USERNAME,
        ),
        password=os.getenv(
            "RABBITMQ_PASSWORD",
            DEFAULT_RABBITMQ_PASSWORD,
        ),
    )

    parameters = pika.ConnectionParameters(
        host=os.getenv(
            "RABBITMQ_HOST",
            DEFAULT_RABBITMQ_HOST,
        ),
        port=int(
            os.getenv(
                "RABBITMQ_PORT",
                str(DEFAULT_RABBITMQ_PORT),
            )
        ),
        credentials=credentials,
        heartbeat=settings.rabbitmq_heartbeat,
        blocked_connection_timeout=settings.rabbitmq_blocked_timeout,
    )

    return pika.BlockingConnection(parameters)


def declare_rabbitmq_topology(
    channel: BlockingChannel,
    config: WorkerConfig | None = None,
) -> None:
    """Declare the main queue and its dead-letter infrastructure."""

    settings = _resolve_config(config)

    channel.exchange_declare(
        exchange=settings.dead_letter_exchange,
        exchange_type="direct",
        durable=True,
    )

    channel.queue_declare(
        queue=settings.dead_letter_queue,
        durable=True,
    )

    channel.queue_bind(
        queue=settings.dead_letter_queue,
        exchange=settings.dead_letter_exchange,
        routing_key=settings.dead_letter_routing_key,
    )

    channel.queue_declare(
        queue=settings.queue_name,
        durable=True,
        arguments={
            "x-dead-letter-exchange": settings.dead_letter_exchange,
            "x-dead-letter-routing-key": settings.dead_letter_routing_key,
        },
    )


def reject_invalid_message(
    channel: BlockingChannel,
    delivery_tag: int,
    error: Exception,
    config: WorkerConfig | None = None,
) -> None:
    """Reject an invalid message and route it to the dead-letter queue."""

    settings = _resolve_config(config)

    logger.error(
        "Rejected invalid message and routed to DLQ '%s': %s",
        settings.dead_letter_queue,
        error,
    )

    channel.basic_nack(
        delivery_tag=delivery_tag,
        requeue=False,
    )


def retry_message(
    channel: BlockingChannel,
    delivery_tag: int,
    error: Exception,
) -> None:
    """Return a temporarily failed message to RabbitMQ."""

    logger.error(
        "Temporary processing failure; message will be retried: %s",
        error,
    )

    channel.basic_nack(
        delivery_tag=delivery_tag,
        requeue=True,
    )
