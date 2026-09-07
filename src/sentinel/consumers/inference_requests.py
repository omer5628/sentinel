import os
import threading

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPError

from sentinel.schema.v1 import InferenceRequestV1


INFERENCE_REQUEST_QUEUE_NAME = "inference_requests"

DEFAULT_RABBITMQ_HOST = "localhost"
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_RABBITMQ_USERNAME = "sentinel"
DEFAULT_RABBITMQ_PASSWORD = "sentinel"


def create_rabbitmq_connection() -> pika.BlockingConnection:
    """Create a RabbitMQ connection for inference requests."""

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
        heartbeat=60,
        blocked_connection_timeout=30,
    )

    return pika.BlockingConnection(
        parameters
    )


class InferenceRequestPublisher:
    """Publish validated inference requests to RabbitMQ."""

    def __init__(self) -> None:
        self.connection: (
            pika.BlockingConnection | None
        ) = None

        self.channel: BlockingChannel | None = None

        self.lock = threading.Lock()

    def _ensure_channel(
        self,
    ) -> BlockingChannel:
        """Return an active RabbitMQ channel."""

        if (
            self.connection is not None
            and self.connection.is_open
            and self.channel is not None
            and self.channel.is_open
        ):
            return self.channel

        self._discard_connection()

        self.connection = (
            create_rabbitmq_connection()
        )

        self.channel = (
            self.connection.channel()
        )

        self.channel.queue_declare(
            queue=INFERENCE_REQUEST_QUEUE_NAME,
            durable=True,
        )

        return self.channel

    def publish(
        self,
        request: InferenceRequestV1,
    ) -> None:
        """Publish one inference request."""

        body = (
            request.model_dump_json()
            .encode("utf-8")
        )

        with self.lock:
            try:
                channel = (
                    self._ensure_channel()
                )

                channel.basic_publish(
                    exchange="",
                    routing_key=(
                        INFERENCE_REQUEST_QUEUE_NAME
                    ),
                    body=body,
                    properties=(
                        pika.BasicProperties(
                            content_type=(
                                "application/json"
                            ),
                            delivery_mode=2,
                        )
                    ),
                )

            except (
                AMQPError,
                OSError,
            ):
                self._discard_connection()
                raise

    def _discard_connection(
        self,
    ) -> None:
        """Close and discard RabbitMQ resources."""

        if (
            self.channel is not None
            and self.channel.is_open
        ):
            try:
                self.channel.close()
            except AMQPError:
                pass

        if (
            self.connection is not None
            and self.connection.is_open
        ):
            try:
                self.connection.close()
            except AMQPError:
                pass

        self.channel = None
        self.connection = None

    def close(self) -> None:
        """Close the publisher connection."""

        with self.lock:
            self._discard_connection()
