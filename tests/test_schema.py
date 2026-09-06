from uuid import UUID

import pytest
from pydantic import ValidationError

from sentinel.schema.v1 import InferenceEventV1


INFERENCE_ID = UUID(
    "12345678-1234-5678-1234-567812345678"
)


def valid_inference_event() -> dict[str, object]:
    """Return a valid inference event payload."""

    return {
        "schema_version": "v1",
        "inference_id": INFERENCE_ID,
        "image_id": "mnist-123",
        "timestamp": 1_700_000_000.0,
        "model_version": "v1",
        "predicted_class": 7,
        "confidence": 0.98,
    }


@pytest.mark.parametrize(
    "model_version",
    [
        "v1",
        "v2",
    ],
)
def test_inference_event_accepts_supported_models(
    model_version: str,
) -> None:
    payload = valid_inference_event()
    payload["model_version"] = model_version

    event = InferenceEventV1.model_validate(
        payload
    )

    assert event.model_version == model_version


@pytest.mark.parametrize(
    "predicted_class",
    [
        -1,
        10,
    ],
)
def test_inference_event_rejects_invalid_predicted_class(
    predicted_class: int,
) -> None:
    payload = valid_inference_event()
    payload["predicted_class"] = predicted_class

    with pytest.raises(ValidationError):
        InferenceEventV1.model_validate(
            payload
        )


@pytest.mark.parametrize(
    "confidence",
    [
        -0.01,
        1.01,
    ],
)
def test_inference_event_rejects_invalid_confidence(
    confidence: float,
) -> None:
    payload = valid_inference_event()
    payload["confidence"] = confidence

    with pytest.raises(ValidationError):
        InferenceEventV1.model_validate(
            payload
        )


def test_inference_event_rejects_invalid_schema_version() -> None:
    payload = valid_inference_event()
    payload["schema_version"] = "v2"

    with pytest.raises(ValidationError):
        InferenceEventV1.model_validate(
            payload
        )


def test_inference_event_rejects_invalid_model_version() -> None:
    payload = valid_inference_event()
    payload["model_version"] = "v3"

    with pytest.raises(ValidationError):
        InferenceEventV1.model_validate(
            payload
        )


def test_inference_event_rejects_extra_fields() -> None:
    payload = valid_inference_event()
    payload["unexpected_field"] = "invalid"

    with pytest.raises(ValidationError):
        InferenceEventV1.model_validate(
            payload
        )
