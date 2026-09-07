from unittest.mock import Mock, patch
from uuid import UUID

from sentinel.consumers.worker import process_message
import psycopg2

EVENT_ID = UUID(
    "12345678-1234-5678-1234-567812345678"
)


def test_inference_publish_failure_does_not_fail_ingestion() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 42

    properties = Mock()
    redis_client = Mock()
    postgres_writer = Mock()

    publisher = Mock()
    publisher.publish.side_effect = RuntimeError(
        "RabbitMQ inference publish failed"
    )

    message = Mock()
    message.event_id = EVENT_ID
    message.image_id = "mnist-123"
    message.timestamp = 1_700_000_000.0

    features = Mock()

    with (
        patch(
            "sentinel.consumers.worker.deserialize_message",
            return_value=message,
        ),
        patch(
            "sentinel.consumers.worker.decode_image",
            return_value=b"image",
        ),
        patch(
            "sentinel.consumers.worker.preprocess_image",
            return_value=features,
        ),
        patch(
            "sentinel.consumers.worker.write_to_redis",
        ),
    ):
        process_message(
            channel=channel,
            method=method,
            properties=properties,
            body=b"message",
            redis_client=redis_client,
            postgres_writer=postgres_writer,
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=publisher,
        )

    channel.basic_ack.assert_called_once_with(
        delivery_tag=42,
    )

    channel.basic_nack.assert_not_called()

    postgres_writer.write.assert_called_once()

    publisher.publish.assert_called_once()

def test_postgres_failure_skips_automatic_inference() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 43

    properties = Mock()
    redis_client = Mock()

    postgres_writer = Mock()
    postgres_writer.write.side_effect = psycopg2.Error(
        "PostgreSQL unavailable"
    )

    publisher = Mock()

    message = Mock()
    message.event_id = EVENT_ID
    message.image_id = "mnist-456"
    message.timestamp = 1_700_000_001.0

    features = Mock()

    with (
        patch(
            "sentinel.consumers.worker.deserialize_message",
            return_value=message,
        ),
        patch(
            "sentinel.consumers.worker.decode_image",
            return_value=b"image",
        ),
        patch(
            "sentinel.consumers.worker.preprocess_image",
            return_value=features,
        ),
        patch(
            "sentinel.consumers.worker.write_to_redis",
        ),
    ):
        process_message(
            channel=channel,
            method=method,
            properties=properties,
            body=b"message",
            redis_client=redis_client,
            postgres_writer=postgres_writer,
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=publisher,
        )

    channel.basic_ack.assert_called_once_with(
        delivery_tag=43,
    )

    publisher.publish.assert_not_called()
