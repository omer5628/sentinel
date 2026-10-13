"""Unit tests for read-only, version-specific Serving smoke tests."""

from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest

from scripts.verify_serving_inference import (
    load_smoke_config,
    make_endpoint_url,
    smoke_test,
    verify_prediction,
)


CONFIG_PATH = Path(__file__).resolve().parents[1] / "conf/serving/mnist.yaml"


def test_builds_model_specific_sample() -> None:
    endpoint, field, payload, classes = load_smoke_config(CONFIG_PATH)
    assert endpoint == "sentinel-mnist"
    assert field == "pixels"
    assert classes == 10
    assert len(payload["pixels"]) == 28
    assert len(payload["pixels"][0]) == 28
    assert payload["pixels"][0][0] == 0.0


def test_builds_direct_version_url_not_canary() -> None:
    assert make_endpoint_url("http://localhost:18080", "sentinel-mnist", 2) == (
        "http://localhost:18080/serve/sentinel-mnist/2"
    )


@pytest.mark.parametrize("version", [0, -1])
def test_rejects_invalid_serving_version(version: int) -> None:
    with pytest.raises(ValueError):
        make_endpoint_url("http://localhost:18080", "sentinel-mnist", version)


@pytest.mark.parametrize("response", [
    {"predicted_class": 2, "confidence": 0.8, "model_version": "v1"},
    {"predicted_class": 10, "confidence": 0.8, "model_version": "v2"},
    {"predicted_class": 1, "confidence": 1.2, "model_version": "v2"},
    {"predicted_class": True, "confidence": 0.8, "model_version": "v2"},
    {"predicted_class": 1, "confidence": 0.8, "model_version": "v2", "logits": [0.0]},
])
def test_rejects_unexpected_prediction(response: dict) -> None:
    with pytest.raises(ValueError):
        verify_prediction(response, "v2", 10)


def test_accepts_valid_response() -> None:
    verify_prediction({
        "predicted_class": 7,
        "confidence": 0.93,
        "model_version": "retrain-35",
        "logits": [0.0] * 10,
    }, "retrain-35", 10)


def test_smoke_test_direct_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            assert timeout > 0

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> Mock:
            calls.append((url, json))
            result = Mock()
            result.raise_for_status.return_value = None
            result.json.return_value = {
                "predicted_class": 7,
                "confidence": 0.9,
                "model_version": "retrain-35",
            }
            return result

    monkeypatch.setattr(httpx, "Client", FakeClient)
    smoke_test(
        CONFIG_PATH,
        "http://localhost:18080",
        35,
        "retrain-35",
        attempts=1,
    )
    assert len(calls) == 1
    assert calls[0][0].endswith("/serve/sentinel-mnist/35")
    assert "canary" not in calls[0][0]


def test_refuses_mismatched_version(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, timeout: float) -> None:
            pass

        def __enter__(self) -> "FakeClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> Mock:
            result = Mock()
            result.raise_for_status.return_value = None
            result.json.return_value = {
                "predicted_class": 7,
                "confidence": 0.9,
                "model_version": "v2",
            }
            return result

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(RuntimeError, match="Serving smoke test failed"):
        smoke_test(CONFIG_PATH, "http://localhost:18080", 35, "retrain-35", attempts=1)
