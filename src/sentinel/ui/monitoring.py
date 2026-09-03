import os

import pika
from pika.exceptions import AMQPError


DEFAULT_RABBITMQ_HOST = "localhost"
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_RABBITMQ_USERNAME = "sentinel"
DEFAULT_RABBITMQ_PASSWORD = "sentinel"

QUEUE_NAME = "video_stream"


def fetch_rabbitmq_status() -> tuple[bool, int, int]:
    """Return RabbitMQ availability, consumer count, and queue depth."""

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
        connection_attempts=1,
        socket_timeout=3,
        blocked_connection_timeout=3,
    )

    connection = None

    try:
        connection = pika.BlockingConnection(parameters)

        channel = connection.channel()

        queue_state = channel.queue_declare(
            queue=QUEUE_NAME,
            passive=True,
        )

        return (
            True,
            int(queue_state.method.consumer_count),
            int(queue_state.method.message_count),
        )

    except (
        AMQPError,
        OSError,
    ):
        return False, 0, 0

    finally:
        if connection is not None and connection.is_open:
            connection.close()