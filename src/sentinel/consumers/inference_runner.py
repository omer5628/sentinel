import logging
import os

import httpx
from pika.adapters.blocking_connection import BlockingChannel
from pika.exceptions import AMQPError
from pika.spec import Basic, BasicProperties
from pydantic import ValidationError

from sentinel.consumers.inference_requests import (
    INFERENCE_REQUEST_QUEUE_NAME,
    INFERENCE_REQUEST_RETRY_QUEUE_NAME,
    create_rabbitmq_connection,
    declare_inference_request_topology,
)
from sentinel.schema.v1 import InferenceRequestV1


DEFAULT_SENTINEL_API_URL = "http://localhost:8000"
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0

MAX_RETRY_ATTEMPTS = 3
RETRY_COUNT_HEADER = "x-sentinel-retry-count"

RETRYABLE_HTTP_STATUS_CODES = {
    408,
    429,
}


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

logger = logging.getLogger(__name__)


def create_api_client() -> httpx.Client:
    """Create a reusable Sentinel API client."""

    return httpx.Client(
        base_url=os.getenv(
            "SENTINEL_API_URL",
            DEFAULT_SENTINEL_API_URL,
        ),
        timeout=DEFAULT_HTTP_TIMEOUT_SECONDS,
    )


def is_retryable_status(
    status_code: int,
) -> bool:
    """Return whether an HTTP response should be retried."""

    return (
        status_code in RETRYABLE_HTTP_STATUS_CODES
        or status_code >= 500
    )


def get_retry_count(
    properties: BasicProperties,
) -> int:
    """Return the current automatic inference retry count."""

    headers = properties.headers

    if not isinstance(headers, dict):
        return 0

    retry_count = headers.get(
        RETRY_COUNT_HEADER,
        0,
    )

    if (
        isinstance(retry_count, int)
        and not isinstance(retry_count, bool)
        and retry_count >= 0
    ):
        return retry_count

    return 0


def create_retry_properties(
    properties: BasicProperties,
    retry_count: int,
) -> BasicProperties:
    """Create persistent properties for a delayed retry."""

    source_headers = properties.headers

    if isinstance(source_headers, dict):
        headers = dict(source_headers)
    else:
        headers = {}

    headers[RETRY_COUNT_HEADER] = retry_count

    content_type = properties.content_type

    if not isinstance(content_type, str):
        content_type = "application/json"

    return BasicProperties(
        content_type=content_type,
        delivery_mode=2,
        headers=headers,
    )


def schedule_retry(
    channel: BlockingChannel,
    delivery_tag: int,
    body: bytes,
    properties: BasicProperties,
    request: InferenceRequestV1,
) -> None:
    """Schedule a delayed retry or dead-letter an exhausted request."""

    current_retry_count = get_retry_count(
        properties
    )

    if current_retry_count >= MAX_RETRY_ATTEMPTS:
        logger.error(
            "Automatic inference exhausted %s retries "
            "for request %s and image %s. "
            "Routing request to DLQ.",
            MAX_RETRY_ATTEMPTS,
            request.request_id,
            request.image_id,
        )

        channel.basic_nack(
            delivery_tag=delivery_tag,
            requeue=False,
        )

        return

    next_retry_count = (
        current_retry_count + 1
    )

    retry_properties = create_retry_properties(
        properties=properties,
        retry_count=next_retry_count,
    )

    try:
        channel.basic_publish(
            exchange="",
            routing_key=(
                INFERENCE_REQUEST_RETRY_QUEUE_NAME
            ),
            body=body,
            properties=retry_properties,
        )

    except (
        AMQPError,
        OSError,
    ) as error:
        logger.error(
            "Failed to schedule automatic inference retry "
            "for request %s and image %s: %s",
            request.request_id,
            request.image_id,
            error,
        )

        channel.basic_nack(
            delivery_tag=delivery_tag,
            requeue=True,
        )

        return

    channel.basic_ack(
        delivery_tag=delivery_tag,
    )

    logger.warning(
        "Scheduled automatic inference retry %s/%s "
        "for request %s and image %s.",
        next_retry_count,
        MAX_RETRY_ATTEMPTS,
        request.request_id,
        request.image_id,
    )


def process_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
    api_client: httpx.Client,
) -> None:
    """Validate an inference request and call the Sentinel API."""

    delivery_tag = method.delivery_tag

    try:
        request = (
            InferenceRequestV1.model_validate_json(
                body
            )
        )

    except ValidationError as error:
        logger.error(
            "Invalid inference request: %s",
            error,
        )

        channel.basic_nack(
            delivery_tag=delivery_tag,
            requeue=False,
        )

        return

    try:
        response = api_client.post(
            f"/predict/{request.image_id}",
            headers={
                "X-Inference-Request-ID": str(
                    request.request_id
                ),
            },
        )

    except httpx.RequestError as error:
        logger.error(
            "Sentinel API request failed for image %s: %s",
            request.image_id,
            error,
        )

        schedule_retry(
            channel=channel,
            delivery_tag=delivery_tag,
            body=body,
            properties=properties,
            request=request,
        )

        return

    if 200 <= response.status_code < 300:
        channel.basic_ack(
            delivery_tag=delivery_tag,
        )

        logger.info(
            "Automatic inference completed for request %s "
            "and image %s.",
            request.request_id,
            request.image_id,
        )

        return

    retryable = is_retryable_status(
        response.status_code
    )

    logger.error(
        "Automatic inference failed for image %s "
        "with HTTP status %s. Retry=%s.",
        request.image_id,
        response.status_code,
        retryable,
    )

    if retryable:
        schedule_retry(
            channel=channel,
            delivery_tag=delivery_tag,
            body=body,
            properties=properties,
            request=request,
        )

        return

    channel.basic_nack(
        delivery_tag=delivery_tag,
        requeue=False,
    )


def run_consumer() -> None:
    """Consume automatic inference requests continuously."""

    rabbitmq_connection = (
        create_rabbitmq_connection()
    )

    channel = (
        rabbitmq_connection.channel()
    )

    declare_inference_request_topology(
        channel
    )

    channel.basic_qos(
        prefetch_count=1,
    )

    api_client = create_api_client()

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
            api_client=api_client,
        )

    channel.basic_consume(
        queue=INFERENCE_REQUEST_QUEUE_NAME,
        on_message_callback=callback,
        auto_ack=False,
    )

    logger.info(
        "Waiting for automatic inference requests on queue '%s'.",
        INFERENCE_REQUEST_QUEUE_NAME,
    )

    try:
        channel.start_consuming()

    except KeyboardInterrupt:
        logger.info(
            "Inference runner stopped by user."
        )

    finally:
        api_client.close()

        if rabbitmq_connection.is_open:
            rabbitmq_connection.close()


def main() -> None:
    """Run the automatic inference consumer."""

    run_consumer()


if __name__ == "__main__":
    main()
