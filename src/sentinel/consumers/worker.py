import logging
import os
from functools import partial

import psycopg2
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from redis import Redis

from sentinel.adapters.preprocessor_factory import (
    Preprocessor,
    create_preprocessor,
)
from sentinel.features import preprocess_image
from sentinel.schema.v1 import ImageMessageV1 as ImageMessageV1

from sentinel.consumers.inference_requests import (
    InferenceRequestPublisher,
)
from sentinel.consumers.worker_messaging import (
    DEAD_LETTER_EXCHANGE as DEAD_LETTER_EXCHANGE,
    DEAD_LETTER_QUEUE as DEAD_LETTER_QUEUE,
    DEAD_LETTER_ROUTING_KEY as DEAD_LETTER_ROUTING_KEY,
    DEFAULT_RABBITMQ_HOST as DEFAULT_RABBITMQ_HOST,
    DEFAULT_RABBITMQ_PASSWORD as DEFAULT_RABBITMQ_PASSWORD,
    DEFAULT_RABBITMQ_PORT as DEFAULT_RABBITMQ_PORT,
    DEFAULT_RABBITMQ_USERNAME as DEFAULT_RABBITMQ_USERNAME,
    QUEUE_NAME as QUEUE_NAME,
    create_rabbitmq_connection as create_rabbitmq_connection,
    declare_rabbitmq_topology as declare_rabbitmq_topology,
    reject_invalid_message as reject_invalid_message,
    retry_message as retry_message,
)
from sentinel.consumers.worker_storage import (
    DEFAULT_POSTGRES_DATABASE as DEFAULT_POSTGRES_DATABASE,
    DEFAULT_POSTGRES_HOST as DEFAULT_POSTGRES_HOST,
    DEFAULT_POSTGRES_PASSWORD as DEFAULT_POSTGRES_PASSWORD,
    DEFAULT_POSTGRES_PORT as DEFAULT_POSTGRES_PORT,
    DEFAULT_POSTGRES_USERNAME as DEFAULT_POSTGRES_USERNAME,
    DEFAULT_REDIS_HOST as DEFAULT_REDIS_HOST,
    DEFAULT_REDIS_PORT as DEFAULT_REDIS_PORT,
    FEATURE_TTL_SECONDS as FEATURE_TTL_SECONDS,
    MODEL_VERSION as MODEL_VERSION,
    PostgresWriter as PostgresWriter,
    create_postgres_connection as create_postgres_connection,
    create_redis_client as create_redis_client,
    tensor_to_json as tensor_to_json,
    write_to_redis as write_to_redis,
)
from sentinel.consumers.worker_config import WorkerConfig
from sentinel.consumers.worker_processing import (
    ProcessingCallbacks,
    process_message as _process_message,
)
from sentinel.consumers.worker_message_contract import (
    SUPPORTED_SCHEMA_VERSION,
    decode_image,
    deserialize_message,
    extract_schema_version as extract_schema_version,
)


SCHEMA_NAME = "image_message"

AUTO_INFERENCE_ENABLED_ENV = "AUTO_INFERENCE_ENABLED"


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)


def is_auto_inference_enabled() -> bool:
    """Return whether automatic inference is enabled."""

    value = os.getenv(
        AUTO_INFERENCE_ENABLED_ENV,
        "false",
    )

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_active_schema_versions() -> frozenset[str]:
    """Load active image-message schema versions from PostgreSQL."""

    connection = create_postgres_connection()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT schema_version
                FROM schema_registry
                WHERE schema_name = %s
                  AND is_active = TRUE
                """,
                (SCHEMA_NAME,),
            )

            rows = cursor.fetchall()

    finally:
        connection.close()

    active_versions = frozenset(str(row[0]) for row in rows)

    if not active_versions:
        raise RuntimeError(
            f"No active schema versions were found for '{SCHEMA_NAME}'."
        )

    return active_versions


def process_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
    redis_client: Redis,
    postgres_writer: PostgresWriter,
    active_schema_versions: frozenset[str],
    inference_request_publisher: (
        InferenceRequestPublisher | None
    ),
    preprocessor: Preprocessor | None = None,
    config: WorkerConfig | None = None,
) -> None:
    """Process a message via the shared handler, preserving legacy hooks."""

    # Resolve dependencies at call time to preserve existing monkeypatch targets.
    selected_preprocessor = (
        preprocess_image if preprocessor is None else preprocessor
    )

    callbacks = ProcessingCallbacks(
        deserialize_message=deserialize_message,
        decode_image=decode_image,
        write_to_redis=(
            write_to_redis
            if config is None
            else partial(write_to_redis, config=config)
        ),
        reject_invalid_message=(
            reject_invalid_message
            if config is None
            else partial(reject_invalid_message, config=config)
        ),
        retry_message=retry_message,
    )

    _process_message(
        channel=channel,
        method=method,
        properties=properties,
        body=body,
        redis_client=redis_client,
        postgres_writer=postgres_writer,
        active_schema_versions=active_schema_versions,
        inference_request_publisher=inference_request_publisher,
        preprocessor=selected_preprocessor,
        callbacks=callbacks,
        logger=logger,
    )


def run_worker() -> None:
    """Consume images and write features to Redis and PostgreSQL."""

    config = WorkerConfig.from_environment()

    logger.info(
        "Loading active schema versions for '%s' from PostgreSQL.",
        SCHEMA_NAME,
    )

    try:
        active_schema_versions = load_active_schema_versions()
    except (psycopg2.Error, RuntimeError) as error:
        logger.critical(
            "Worker cannot start because the Schema Registry is unavailable "
            "or has no active schemas: %s",
            error,
        )
        raise

    logger.info(
        "Loaded active schema versions: %s",
        ", ".join(sorted(active_schema_versions)),
    )

    if SUPPORTED_SCHEMA_VERSION not in active_schema_versions:
        raise RuntimeError(
            f"Required schema version '{SUPPORTED_SCHEMA_VERSION}' "
            "is not active."
        )

    # Resolve the preprocessing adapter once during Worker startup.
    preprocessor = create_preprocessor()
    logger.info(
        "Using preprocessing adapter: %s",
        type(preprocessor).__name__,
    )

    logger.info("Connecting to Redis.")
    redis_client = create_redis_client()

    postgres_writer = PostgresWriter()

    try:
        postgres_writer.ensure_connection()
        logger.info("Connected to PostgreSQL.")
    except psycopg2.Error as error:
        logger.error(
            "PostgreSQL is unavailable after schema initialization. "
            "The Worker will continue in partial failure mode: %s",
            error,
        )

    inference_request_publisher: (
        InferenceRequestPublisher | None
    ) = None

    if is_auto_inference_enabled():
        inference_request_publisher = (
            InferenceRequestPublisher()
        )

        logger.info(
            "Automatic inference is enabled."
        )
    else:
        logger.info(
            "Automatic inference is disabled."
        )

    logger.info("Connecting to RabbitMQ.")
    rabbitmq_connection = create_rabbitmq_connection(config=config)

    channel = rabbitmq_connection.channel()

    declare_rabbitmq_topology(channel, config=config)

    channel.basic_qos(
        prefetch_count=config.prefetch_count,
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
            active_schema_versions=active_schema_versions,
            inference_request_publisher=(
                inference_request_publisher
            ),
            preprocessor=preprocessor,
            config=config,
        )

    channel.basic_consume(
        queue=config.queue_name,
        on_message_callback=callback,
        auto_ack=False,
    )

    logger.info(
        "Worker started. Waiting for messages from queue '%s'.",
        config.queue_name,
    )

    try:
        channel.start_consuming()

    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")

        if channel.is_open:
            channel.stop_consuming()

    finally:
        if inference_request_publisher is not None:
            inference_request_publisher.close()

        postgres_writer.close()
        redis_client.close()

        if rabbitmq_connection.is_open:
            rabbitmq_connection.close()


def main() -> None:
    """Run the Sentinel ingestion worker."""

    run_worker()


if __name__ == "__main__":
    main()