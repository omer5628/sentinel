
"""Tests for configurable Worker preprocessing injection."""

from unittest.mock import Mock, patch
from uuid import UUID

from sentinel.consumers.worker import process_message


EVENT_ID = UUID(
    "12345678-1234-5678-1234-567812345678"
)


def test_process_message_uses_injected_preprocessor() -> None:
    """Use the injected adapter instead of the legacy preprocessor."""

    channel = Mock()
    method = Mock()
    method.delivery_tag = 44

    redis_client = Mock()
    postgres_writer = Mock()

    message = Mock()
    message.event_id = EVENT_ID
    message.image_id = "test-image"

    features = Mock()
    injected_preprocessor = Mock(return_value=features)

    raw_image = b"test-image-bytes"

    with (
        patch(
            "sentinel.consumers.worker.deserialize_message",
            return_value=message,
        ),
        patch(
            "sentinel.consumers.worker.decode_image",
            return_value=raw_image,
        ),
        patch(
            "sentinel.consumers.worker.preprocess_image",
        ) as legacy_preprocessor,
        patch(
            "sentinel.consumers.worker.write_to_redis",
        ) as write_to_redis,
    ):
        process_message(
            channel=channel,
            method=method,
            properties=Mock(),
            body=b"message",
            redis_client=redis_client,
            postgres_writer=postgres_writer,
            active_schema_versions=frozenset({"v1"}),
            inference_request_publisher=None,
            preprocessor=injected_preprocessor,
        )

    injected_preprocessor.assert_called_once_with(
        raw_image
    )

    legacy_preprocessor.assert_not_called()

    write_to_redis.assert_called_once_with(
        redis_client=redis_client,
        image_id="test-image",
        tensor=features,
    )

    postgres_writer.write.assert_called_once_with(
        event_id=str(EVENT_ID),
        image_id="test-image",
        raw_image=raw_image,
        tensor=features,
    )

    channel.basic_ack.assert_called_once_with(
        delivery_tag=44,
    )

    channel.basic_nack.assert_not_called()
