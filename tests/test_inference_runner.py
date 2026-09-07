from unittest.mock import Mock
from uuid import UUID

import httpx
from pika.spec import BasicProperties

from sentinel.consumers.inference_requests import (
    INFERENCE_REQUEST_RETRY_QUEUE_NAME,
)
from sentinel.consumers.inference_runner import (
    MAX_RETRY_ATTEMPTS,
    RETRY_COUNT_HEADER,
    process_message,
)
from sentinel.schema.v1 import InferenceRequestV1


REQUEST_ID = UUID(
    "87654321-4321-8765-4321-876543218765"
)


def request_body() -> bytes:
    """Return a valid inference request body."""

    request = InferenceRequestV1(
        schema_version="v1",
        request_id=REQUEST_ID,
        image_id="mnist-123",
        timestamp=1_700_000_000.0,
    )

    return request.model_dump_json().encode("utf-8")


def message_properties(
    retry_count: int = 0,
) -> BasicProperties:
    """Return inference request message properties."""

    headers: dict[str, int] = {}

    if retry_count > 0:
        headers[RETRY_COUNT_HEADER] = (
            retry_count
        )

    return BasicProperties(
        content_type="application/json",
        delivery_mode=2,
        headers=headers,
    )


def test_successful_inference_acknowledges_message() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 10

    api_client = Mock()

    response = Mock()
    response.status_code = 200

    api_client.post.return_value = response

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(),
        body=request_body(),
        api_client=api_client,
    )

    api_client.post.assert_called_once_with(
        "/predict/mnist-123",
        headers={
            "X-Inference-Request-ID": str(
                REQUEST_ID
            ),
        },
    )

    channel.basic_ack.assert_called_once_with(
        delivery_tag=10,
    )

    channel.basic_nack.assert_not_called()
    channel.basic_publish.assert_not_called()


def test_invalid_request_is_rejected() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 11

    api_client = Mock()

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(),
        body=b'{"invalid": true}',
        api_client=api_client,
    )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=11,
        requeue=False,
    )

    channel.basic_publish.assert_not_called()
    api_client.post.assert_not_called()


def test_server_error_is_scheduled_for_retry() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 12

    api_client = Mock()

    response = Mock()
    response.status_code = 503

    api_client.post.return_value = response

    body = request_body()

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(),
        body=body,
        api_client=api_client,
    )

    channel.basic_publish.assert_called_once()

    publish_args = (
        channel.basic_publish.call_args.kwargs
    )

    assert publish_args["exchange"] == ""
    assert (
        publish_args["routing_key"]
        == INFERENCE_REQUEST_RETRY_QUEUE_NAME
    )
    assert publish_args["body"] == body

    retry_properties = (
        publish_args["properties"]
    )

    assert (
        retry_properties.headers[
            RETRY_COUNT_HEADER
        ]
        == 1
    )

    assert retry_properties.delivery_mode == 2

    channel.basic_ack.assert_called_once_with(
        delivery_tag=12,
    )

    channel.basic_nack.assert_not_called()


def test_client_error_is_rejected() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 13

    api_client = Mock()

    response = Mock()
    response.status_code = 404

    api_client.post.return_value = response

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(),
        body=request_body(),
        api_client=api_client,
    )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=13,
        requeue=False,
    )

    channel.basic_publish.assert_not_called()
    channel.basic_ack.assert_not_called()


def test_network_failure_is_scheduled_for_retry() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 14

    api_client = Mock()

    request = httpx.Request(
        "POST",
        "http://sentinel-api:8000/predict/mnist-123",
    )

    api_client.post.side_effect = (
        httpx.ConnectError(
            "Connection failed",
            request=request,
        )
    )

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(),
        body=request_body(),
        api_client=api_client,
    )

    channel.basic_publish.assert_called_once()

    publish_args = (
        channel.basic_publish.call_args.kwargs
    )

    assert (
        publish_args["routing_key"]
        == INFERENCE_REQUEST_RETRY_QUEUE_NAME
    )

    assert (
        publish_args["properties"].headers[
            RETRY_COUNT_HEADER
        ]
        == 1
    )

    channel.basic_ack.assert_called_once_with(
        delivery_tag=14,
    )

    channel.basic_nack.assert_not_called()


def test_retry_count_is_incremented() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 15

    api_client = Mock()

    response = Mock()
    response.status_code = 503

    api_client.post.return_value = response

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(
            retry_count=2
        ),
        body=request_body(),
        api_client=api_client,
    )

    publish_args = (
        channel.basic_publish.call_args.kwargs
    )

    assert (
        publish_args["properties"].headers[
            RETRY_COUNT_HEADER
        ]
        == 3
    )

    channel.basic_ack.assert_called_once_with(
        delivery_tag=15,
    )

    channel.basic_nack.assert_not_called()


def test_exhausted_retries_are_dead_lettered() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 16

    api_client = Mock()

    response = Mock()
    response.status_code = 503

    api_client.post.return_value = response

    process_message(
        channel=channel,
        method=method,
        properties=message_properties(
            retry_count=MAX_RETRY_ATTEMPTS
        ),
        body=request_body(),
        api_client=api_client,
    )

    channel.basic_publish.assert_not_called()
    channel.basic_ack.assert_not_called()

    channel.basic_nack.assert_called_once_with(
        delivery_tag=16,
        requeue=False,
    )
