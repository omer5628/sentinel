
"""Process incoming messages for the Sentinel ingestion Worker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

import psycopg2
import redis
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from redis import Redis

from sentinel.adapters.preprocessor_factory import Preprocessor
from sentinel.consumers.inference_requests import (
    InferenceRequestPublisher,
)
from sentinel.consumers.worker_storage import PostgresWriter
from sentinel.schema.v1 import (
    ImageMessageV1,
    InferenceRequestV1,
)


@dataclass(frozen=True)
class ProcessingCallbacks:
    """Provide message-processing operations without module coupling."""

    deserialize_message: Callable[..., ImageMessageV1]
    decode_image: Callable[..., bytes]
    write_to_redis: Callable[..., None]
    reject_invalid_message: Callable[..., None]
    retry_message: Callable[..., None]


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
    preprocessor: Preprocessor,
    callbacks: ProcessingCallbacks,
    logger: logging.Logger,
) -> None:
    """Validate, preprocess, store, and acknowledge one message."""

    del properties

    delivery_tag = method.delivery_tag

    try:
        message = callbacks.deserialize_message(
            body=body,
            active_schema_versions=active_schema_versions,
        )

        raw_image = callbacks.decode_image(message)

        event_id = str(message.event_id)
        image_id = message.image_id

        features = preprocessor(raw_image)

    except ValueError as error:
        callbacks.reject_invalid_message(
            channel=channel,
            delivery_tag=delivery_tag,
            error=error,
        )
        return

    except Exception as error:
        callbacks.retry_message(
            channel=channel,
            delivery_tag=delivery_tag,
            error=error,
        )
        return

    try:
        callbacks.write_to_redis(
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

    channel.basic_ack(
        delivery_tag=delivery_tag,
    )

    if postgres_written:
        logger.info(
            "Processed event %s for image %s. "
            "Redis=success, PostgreSQL=success.",
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

    if (
        inference_request_publisher is None
        or not postgres_written
    ):
        return

    try:
        inference_request = InferenceRequestV1(
            schema_version="v1",
            request_id=message.event_id,
            image_id=image_id,
            timestamp=message.timestamp,
        )

        inference_request_publisher.publish(
            inference_request
        )

        logger.info(
            "Published automatic inference request "
            "for event %s and image %s.",
            event_id,
            image_id,
        )

    except Exception as error:
        logger.warning(
            "Automatic inference request failed for event %s "
            "and image %s. Ingestion remains successful: %s",
            event_id,
            image_id,
            error,
        )
