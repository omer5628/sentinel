
"""Regression tests for the existing Worker message-processing behavior."""

from unittest.mock import Mock, patch
from uuid import UUID

import pytest
import redis

from sentinel.consumers.worker import process_message


EVENT_ID = UUID("12345678-1234-5678-1234-567812345678")


@pytest.mark.parametrize(
    ("error", "expected_requeue"),
    [
        (ValueError("Invalid message"), False),
        (RuntimeError("Temporary failure"), True),
    ],
)
def test_message_failure_preserves_nack_policy(
    error: Exception,
    expected_requeue: bool,
) -> None:
    """Invalid messages go to DLQ; temporary failures are retried."""

    channel = Mock()
    method = Mock()
    method.delivery_tag = 42

    postgres_writer = Mock()
    publisher = Mock()

    with patch(
        "sentinel.consumers.worker.deserialize_message",
        side_effect=error,
    ):
        process_message(
            channel=channel,
            method=method,
            properties=Mock(),
            body=b"message",
            redis_client=Mock(),
            postgres_writer=postgres_writer,
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=publisher,
        )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=42,
        requeue=expected_requeue,
    )
    channel.basic_ack.assert_not_called()
    postgres_writer.write.assert_not_called()
    publisher.publish.assert_not_called()


def test_redis_failure_preserves_retry_policy() -> None:
    """A Redis failure must retry without writing to PostgreSQL."""

    channel = Mock()
    method = Mock()
    method.delivery_tag = 43

    postgres_writer = Mock()
    publisher = Mock()

    message = Mock()
    message.event_id = EVENT_ID
    message.image_id = "test-image"

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
            return_value=Mock(),
        ),
        patch(
            "sentinel.consumers.worker.write_to_redis",
            side_effect=redis.RedisError("Redis unavailable"),
        ),
    ):
        process_message(
            channel=channel,
            method=method,
            properties=Mock(),
            body=b"message",
            redis_client=Mock(),
            postgres_writer=postgres_writer,
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=publisher,
        )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=43,
        requeue=True,
    )
    channel.basic_ack.assert_not_called()
    postgres_writer.write.assert_not_called()
    publisher.publish.assert_not_called()
