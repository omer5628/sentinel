
import logging
import os
from datetime import datetime, timezone

import pika
import psycopg2
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from psycopg2.extensions import connection as PostgreSQLConnection
from pydantic import ValidationError

from sentinel.schema.v1 import InferenceEventV1


QUEUE_NAME = "inference_events"

DEFAULT_RABBITMQ_HOST = "localhost"
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_RABBITMQ_USERNAME = "sentinel"
DEFAULT_RABBITMQ_PASSWORD = "sentinel"

DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DATABASE = "sentinel"
DEFAULT_POSTGRES_USERNAME = "sentinel"
DEFAULT_POSTGRES_PASSWORD = "sentinel"


logging.basicConfig(
    level=os.getenv(
        "LOG_LEVEL",
        "INFO",
    ),
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    ),
)

logger = logging.getLogger(
    __name__
)


def create_rabbitmq_connection() -> pika.BlockingConnection:
    """Create a RabbitMQ connection."""

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


class InferenceLogWriter:
    """Write inference events to PostgreSQL."""

    def __init__(self) -> None:
        self.connection: (
            PostgreSQLConnection | None
        ) = None

    def ensure_connection(
        self,
    ) -> PostgreSQLConnection:
        """Return an active PostgreSQL connection."""

        if (
            self.connection is None
            or self.connection.closed
        ):
            self.connection = (
                create_postgres_connection()
            )

        return self.connection

    def write(
        self,
        event: InferenceEventV1,
    ) -> None:
        """Persist one inference event."""

        connection = (
            self.ensure_connection()
        )

        event_time = datetime.fromtimestamp(
            event.timestamp,
            tz=timezone.utc,
        )

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO inference_log (
                        inference_id,
                        image_id,
                        model_version,
                        predicted_class,
                        confidence,
                        created_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (inference_id)
                    DO NOTHING
                    """,
                    (
                        str(
                            event.inference_id
                        ),
                        event.image_id,
                        event.model_version,
                        event.predicted_class,
                        event.confidence,
                        event_time,
                    ),
                )

            connection.commit()

        except psycopg2.Error:
            self._discard_connection()
            raise

    def _discard_connection(
        self,
    ) -> None:
        """Discard a failed PostgreSQL connection."""

        if self.connection is None:
            return

        try:
            self.connection.rollback()
        except psycopg2.Error:
            pass

        try:
            self.connection.close()
        except psycopg2.Error:
            pass

        self.connection = None

    def close(
        self,
    ) -> None:
        """Close the PostgreSQL connection."""

        if (
            self.connection is not None
            and not self.connection.closed
        ):
            self.connection.close()

        self.connection = None


def process_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
    writer: InferenceLogWriter,
) -> None:
    """Validate and persist one inference event."""

    del properties

    try:
        event = (
            InferenceEventV1.model_validate_json(
                body
            )
        )

    except ValidationError as error:
        logger.error(
            "Invalid inference event: %s",
            error,
        )

        channel.basic_nack(
            delivery_tag=(
                method.delivery_tag
            ),
            requeue=False,
        )

        return

    try:
        writer.write(
            event
        )

    except psycopg2.Error as error:
        logger.error(
            "Failed to persist inference event: %s",
            error,
        )

        channel.basic_nack(
            delivery_tag=(
                method.delivery_tag
            ),
            requeue=True,
        )

        return

    channel.basic_ack(
        delivery_tag=(
            method.delivery_tag
        )
    )

    logger.info(
        (
            "Stored inference_id=%s "
            "image_id=%s model=%s"
        ),
        event.inference_id,
        event.image_id,
        event.model_version,
    )


def run_consumer() -> None:
    """Consume inference events continuously."""

    rabbitmq_connection = (
        create_rabbitmq_connection()
    )

    channel = (
        rabbitmq_connection.channel()
    )

    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
    )

    channel.basic_qos(
        prefetch_count=10,
    )

    writer = InferenceLogWriter()

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
            writer=writer,
        )

    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=callback,
        auto_ack=False,
    )

    logger.info(
        "Waiting for inference events on queue '%s'.",
        QUEUE_NAME,
    )

    try:
        channel.start_consuming()

    except KeyboardInterrupt:
        logger.info(
            "Inference logger stopped by user."
        )

    finally:
        writer.close()

        if rabbitmq_connection.is_open:
            rabbitmq_connection.close()


def main() -> None:
    """Run the inference log consumer."""

    run_consumer()


if __name__ == "__main__":
    main()