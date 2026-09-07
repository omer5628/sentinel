from unittest.mock import Mock
from uuid import UUID

import httpx

from sentinel.consumers.inference_runner import (
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
        properties=Mock(),
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


def test_invalid_request_is_rejected() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 11

    api_client = Mock()

    process_message(
        channel=channel,
        method=method,
        properties=Mock(),
        body=b'{"invalid": true}',
        api_client=api_client,
    )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=11,
        requeue=False,
    )

    api_client.post.assert_not_called()


def test_server_error_is_retried() -> None:
    channel = Mock()

    method = Mock()
    method.delivery_tag = 12

    api_client = Mock()

    response = Mock()
    response.status_code = 503

    api_client.post.return_value = response

    process_message(
        channel=channel,
        method=method,
        properties=Mock(),
        body=request_body(),
        api_client=api_client,
    )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=12,
        requeue=True,
    )


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
        properties=Mock(),
        body=request_body(),
        api_client=api_client,
    )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=13,
        requeue=False,
    )


def test_network_failure_is_retried() -> None:
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
        properties=Mock(),
        body=request_body(),
        api_client=api_client,
    )

    channel.basic_nack.assert_called_once_with(
        delivery_tag=14,
        requeue=True,
    )
