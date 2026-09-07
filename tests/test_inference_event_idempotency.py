from unittest.mock import Mock, patch
from uuid import UUID
from fastapi.testclient import TestClient
from sentinel.serving.api import (
    ClearMLPrediction,
    app,
    application_state,
    publish_inference_event,
)


INFERENCE_ID = UUID(
    "87654321-4321-8765-4321-876543218765"
)

GENERATED_INFERENCE_ID = UUID(
    "12345678-1234-5678-1234-567812345678"
)

def test_publish_uses_supplied_inference_id() -> None:
    original_publisher = (
        application_state.inference_event_publisher
    )

    publisher = Mock()

    application_state.inference_event_publisher = (
        publisher
    )

    try:
        publish_inference_event(
            image_id="mnist-123",
            model_version="v1",
            predicted_class=7,
            confidence=0.98,
            inference_id=INFERENCE_ID,
        )

        publisher.publish.assert_called_once()

        event = publisher.publish.call_args.args[0]

        assert event.inference_id == INFERENCE_ID
        assert event.image_id == "mnist-123"

    finally:
        application_state.inference_event_publisher = (
            original_publisher
        )


def test_publish_generates_id_when_none_is_supplied() -> None:
    original_publisher = (
        application_state.inference_event_publisher
    )

    publisher = Mock()

    application_state.inference_event_publisher = (
        publisher
    )

    try:
        with patch(
            "sentinel.serving.api.uuid4",
            return_value=GENERATED_INFERENCE_ID,
        ):
            publish_inference_event(
                image_id="mnist-456",
                model_version="v2",
                predicted_class=4,
                confidence=0.95,
            )

        publisher.publish.assert_called_once()

        event = publisher.publish.call_args.args[0]

        assert (
            event.inference_id
            == GENERATED_INFERENCE_ID
        )

    finally:
        application_state.inference_event_publisher = (
            original_publisher
        )

def test_predict_header_is_forwarded_as_inference_id() -> None:
    original_redis_client = (
        application_state.redis_client
    )

    original_clearml_client = (
        application_state.clearml_client
    )

    redis_client = Mock()
    redis_client.get.return_value = b"feature"

    application_state.redis_client = (
        redis_client
    )

    application_state.clearml_client = Mock()

    try:
        with (
            patch(
                "sentinel.serving.api.deserialize_feature",
                return_value=Mock(),
            ),
            patch(
                "sentinel.serving.api.run_canary_inference",
                return_value=ClearMLPrediction(
                    predicted_class=7,
                    confidence=0.98,
                    model_version="v1",
                ),
            ),
            patch(
                "sentinel.serving.api.publish_inference_event"
            ) as publish_mock,
        ):
            client = TestClient(app)

            try:
                response = client.post(
                    "/predict/mnist-123",
                    headers={
                        "X-Inference-Request-ID": str(
                            INFERENCE_ID
                        ),
                    },
                )
            finally:
                client.close()

        assert response.status_code == 200

        publish_mock.assert_called_once_with(
            image_id="mnist-123",
            model_version="v1",
            predicted_class=7,
            confidence=0.98,
            inference_id=INFERENCE_ID,
        )

    finally:
        application_state.redis_client = (
            original_redis_client
        )

        application_state.clearml_client = (
            original_clearml_client
        )
