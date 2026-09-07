from unittest.mock import Mock, patch
from uuid import UUID

from sentinel.consumers.inference_requests import (
    INFERENCE_REQUEST_DEAD_LETTER_EXCHANGE,
    INFERENCE_REQUEST_DEAD_LETTER_QUEUE,
    INFERENCE_REQUEST_DEAD_LETTER_ROUTING_KEY,
    INFERENCE_REQUEST_QUEUE_NAME,
    InferenceRequestPublisher,
)
from sentinel.schema.v1 import InferenceRequestV1


def test_publish_inference_request() -> None:
    request = InferenceRequestV1(
        schema_version="v1",
        request_id=UUID(
            "87654321-4321-8765-4321-876543218765"
        ),
        image_id="mnist-123",
        timestamp=1_700_000_000.0,
    )

    channel = Mock()
    channel.is_open = True

    connection = Mock()
    connection.is_open = True
    connection.channel.return_value = channel

    with patch(
        "sentinel.consumers.inference_requests."
        "create_rabbitmq_connection",
        return_value=connection,
    ):
        publisher = InferenceRequestPublisher()

        publisher.publish(
            request
        )

    channel.exchange_declare.assert_called_once_with(
        exchange=INFERENCE_REQUEST_DEAD_LETTER_EXCHANGE,
        exchange_type="direct",
        durable=True,
    )

    channel.queue_bind.assert_called_once_with(
        queue=INFERENCE_REQUEST_DEAD_LETTER_QUEUE,
        exchange=INFERENCE_REQUEST_DEAD_LETTER_EXCHANGE,
        routing_key=INFERENCE_REQUEST_DEAD_LETTER_ROUTING_KEY,
    )

    assert channel.queue_declare.call_count == 2

    channel.queue_declare.assert_any_call(
        queue=INFERENCE_REQUEST_DEAD_LETTER_QUEUE,
        durable=True,
    )

    channel.queue_declare.assert_any_call(
        queue=INFERENCE_REQUEST_QUEUE_NAME,
        durable=True,
        arguments={
            "x-dead-letter-exchange": (
                INFERENCE_REQUEST_DEAD_LETTER_EXCHANGE
            ),
            "x-dead-letter-routing-key": (
                INFERENCE_REQUEST_DEAD_LETTER_ROUTING_KEY
            ),
        },
    )

    channel.basic_publish.assert_called_once()

    publish_args = (
        channel.basic_publish.call_args.kwargs
    )

    assert publish_args["exchange"] == ""
    assert (
        publish_args["routing_key"]
        == INFERENCE_REQUEST_QUEUE_NAME
    )

    assert publish_args["body"] == (
        request.model_dump_json()
        .encode("utf-8")
    )

    properties = publish_args["properties"]

    assert properties.content_type == "application/json"
    assert properties.delivery_mode == 2
