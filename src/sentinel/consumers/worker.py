import base64
import binascii
import json
import logging
import os
from typing import Any

import pika
import psycopg2
import redis
import torch
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from psycopg2.extensions import connection as PostgreSQLConnection
from redis import Redis

from sentinel.features import preprocess_image


QUEUE_NAME = "video_stream"
FEATURE_TTL_SECONDS = 3600
MODEL_VERSION = "v1"

DEFAULT_RABBITMQ_HOST = "localhost"
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_RABBITMQ_USERNAME = "sentinel"
DEFAULT_RABBITMQ_PASSWORD = "sentinel"

DEFAULT_REDIS_HOST = "localhost"
DEFAULT_REDIS_PORT = 6379

DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DATABASE = "sentinel"
DEFAULT_POSTGRES_USERNAME = "sentinel"
DEFAULT_POSTGRES_PASSWORD = "sentinel"


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=("%(asctime)s | %(levelname)s | %(name)s | %(message)s"),
)

logger = logging.getLogger(__name__)


def create_rabbitmq_connection() -> pika.BlockingConnection:
    """Create a connection to RabbitMQ."""

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

    return pika.BlockingConnection(parameters)


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


def deserialize_message(body: bytes) -> dict[str, Any]:
    """Deserialize and validate an incoming RabbitMQ message."""

    try:
        message = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Message body is not valid JSON.") from error

    if not isinstance(message, dict):
        raise ValueError("Message body must contain a JSON object.")

    required_fields = {
        "event_id",
        "image_id",
        "image_base64",
    }

    missing_fields = required_fields.difference(message)

    if missing_fields:
        missing = ", ".join(sorted(missing_fields))

        raise ValueError(f"Message is missing required fields: {missing}")

    return message


def decode_image(message: dict[str, Any]) -> bytes:
    """Decode a Base64 image from a RabbitMQ message."""

    encoded_image = message["image_base64"]

    if not isinstance(encoded_image, str):
        raise ValueError("The image_base64 field must be a string.")

    try:
        return base64.b64decode(
            encoded_image,
            validate=True,
        )
    except (binascii.Error, ValueError) as error:
        raise ValueError("The image is not valid Base64.") from error


def tensor_to_json(tensor: torch.Tensor) -> str:
    """Serialize a tensor as JSON for PostgreSQL storage."""

    return json.dumps(tensor.detach().cpu().tolist())


def write_to_redis(
    redis_client: Redis,
    image_id: str,
    tensor: torch.Tensor,
) -> None:
    """Write the latest feature tensor to Redis."""

    redis_key = f"feat:{image_id}"

    redis_client.setex(
        name=redis_key,
        time=FEATURE_TTL_SECONDS,
        value=tensor.detach().cpu().numpy().tobytes(),
    )


def reject_invalid_message(
    channel: BlockingChannel,
    delivery_tag: int,
    error: Exception,
) -> None:
    """Reject a permanently invalid message without retrying it."""

    logger.error(
        "Rejected invalid message: %s",
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


def process_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
    redis_client: Redis,
    postgres_writer: PostgresWriter,
) -> None:
    """Process one image message and perform the dual-write."""

    del properties

    delivery_tag = method.delivery_tag

    try:
        message = deserialize_message(body)
        raw_image = decode_image(message)

        event_id = str(message["event_id"])
        image_id = str(message["image_id"])

        features = preprocess_image(raw_image)

    except ValueError as error:
        reject_invalid_message(
            channel=channel,
            delivery_tag=delivery_tag,
            error=error,
        )
        return

    except Exception as error:
        retry_message(
            channel=channel,
            delivery_tag=delivery_tag,
            error=error,
        )
        return

    # Redis is required for the Online Hot Path.
    # If this write fails, retry the entire event.
    try:
        write_to_redis(
            redis_client=redis_client,
            image_id=image_id,
            tensor=features,
        )

    except redis.RedisError as error:
        logger.error(
            "Redis write failed for event %s and image %s: %s",
            event_id,
            image_id,
            error,
        )

        channel.basic_nack(
            delivery_tag=delivery_tag,
            requeue=True,
        )
        return

    postgres_written = True

    # PostgreSQL belongs to the Offline Cold Path.
    # Its failure must not block Redis or the Serving API.
    try:
        postgres_writer.write(
            event_id=event_id,
            image_id=image_id,
            raw_image=raw_image,
            tensor=features,
        )

    except psycopg2.Error as error:
        postgres_written = False

        logger.error(
            "PostgreSQL write failed for event %s and image %s. "
            "The feature remains available in Redis: %s",
            event_id,
            image_id,
            error,
        )

    # Redis succeeded, so acknowledge the RabbitMQ message.
    channel.basic_ack(
        delivery_tag=delivery_tag,
    )

    if postgres_written:
        logger.info(
            "Processed event %s for image %s. Redis=success, PostgreSQL=success.",
            event_id,
            image_id,
        )
    else:
        logger.warning(
            "Processed event %s for image %s in partial failure mode. "
            "Redis=success, PostgreSQL=failed.",
            event_id,
            image_id,
        )


def run_worker() -> None:
    """Consume images and write features to Redis and PostgreSQL."""

    logger.info("Connecting to Redis.")
    redis_client = create_redis_client()

    postgres_writer = PostgresWriter()

    try:
        postgres_writer.ensure_connection()
        logger.info("Connected to PostgreSQL.")
    except psycopg2.Error as error:
        logger.error(
            "PostgreSQL is unavailable during startup. "
            "The Worker will continue in partial failure mode: %s",
            error,
        )

    logger.info("Connecting to RabbitMQ.")
    rabbitmq_connection = create_rabbitmq_connection()

    channel = rabbitmq_connection.channel()

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
    )

    channel.basic_qos(
        prefetch_count=1,
    )

    def callback(
        callback_channel: BlockingChannel,
        method: Basic.Deliver,
        properties: BasicProperties,
        body: bytes,
    ) -> None:
        process_message(
            channel=callback_channel,
            method=method,
            properties=properties,
            body=body,
            redis_client=redis_client,
            postgres_writer=postgres_writer,
        )

    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=callback,
        auto_ack=False,
    )

    logger.info(
        "Worker started. Waiting for messages from queue '%s'.",
        QUEUE_NAME,
    )

    try:
        channel.start_consuming()

    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")

        if channel.is_open:
            channel.stop_consuming()

    finally:
        postgres_writer.close()
        redis_client.close()

        if rabbitmq_connection.is_open:
            rabbitmq_connection.close()


def main() -> None:
    """Run the Sentinel ingestion worker."""

    run_worker()


if __name__ == "__main__":
    main()
