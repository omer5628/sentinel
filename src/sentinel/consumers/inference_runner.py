import logging
import os

import httpx
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties
from pydantic import ValidationError

from sentinel.consumers.inference_requests import (
    INFERENCE_REQUEST_QUEUE_NAME,
    create_rabbitmq_connection,
    declare_inference_request_topology,
)
from sentinel.schema.v1 import InferenceRequestV1


DEFAULT_SENTINEL_API_URL = "http://localhost:8000"
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0

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


def process_message(
    channel: BlockingChannel,
    method: Basic.Deliver,
    properties: BasicProperties,
    body: bytes,
    api_client: httpx.Client,
) -> None:
    """Validate an inference request and call the Sentinel API."""

    del properties

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
            f"/predict/{request.image_id}"
        )

    except httpx.RequestError as error:
        logger.error(
            "Sentinel API request failed for image %s: %s",
            request.image_id,
            error,
        )

        channel.basic_nack(
            delivery_tag=delivery_tag,
            requeue=True,
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

    channel.basic_nack(
        delivery_tag=delivery_tag,
        requeue=retryable,
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
