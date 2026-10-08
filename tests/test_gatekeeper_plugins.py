from pathlib import Path
from typing import Any

import pytest

from sentinel.gatekeeper.contracts import (
    GoldenSample,
)
from sentinel.gatekeeper.plugins import (
    load_golden_set_adapter,
    load_model_adapter,
    load_model_artifact_resolver,
    load_plugin_object,
)


class FakeGoldenSetAdapter:
    """Provide a valid golden-set adapter for plugin tests."""

    def load(
        self,
        dataset_path: Path,
    ) -> list[GoldenSample]:
        return [
            GoldenSample(
                features=str(dataset_path),
                label="expected",
            )
        ]


class FakeModelAdapter:
    """Provide a valid model adapter for plugin tests."""

    def load(
        self,
        model_reference: str,
    ) -> str:
        return model_reference

    def predict(
        self,
        model: Any,
        features: Any,
    ) -> str:
        return "prediction"


class FakeModelArtifactResolver:
    """Provide a valid model-artifact resolver for plugin tests."""

    def resolve(
        self,
        model_reference: str,
    ) -> str:
        return f"/tmp/{model_reference}.pt"


class InvalidAdapter:
    """Represent a plugin that does not satisfy adapter contracts."""

    pass


def test_load_plugin_object() -> None:
    loaded_object = load_plugin_object(
        "sentinel.gatekeeper.metrics:accuracy_metric"
    )

    assert callable(
        loaded_object
    )


def test_load_plugin_object_rejects_invalid_reference() -> None:
    with pytest.raises(
        ValueError,
        match="module:attribute",
    ):
        load_plugin_object(
            "invalid-reference"
        )


def test_load_plugin_object_rejects_missing_attribute() -> None:
    with pytest.raises(
        ImportError,
        match="attribute was not found",
    ):
        load_plugin_object(
            "sentinel.gatekeeper.metrics:missing_metric"
        )


def test_load_golden_set_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.gatekeeper.plugins.load_plugin_object",
        lambda reference: FakeGoldenSetAdapter,
    )

    adapter = load_golden_set_adapter(
        "fake.module:FakeGoldenSetAdapter"
    )

    samples = adapter.load(
        Path("golden.csv")
    )

    assert len(samples) == 1
    assert samples[0].label == "expected"


def test_load_model_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.gatekeeper.plugins.load_plugin_object",
        lambda reference: FakeModelAdapter,
    )

    adapter = load_model_adapter(
        "fake.module:FakeModelAdapter"
    )

    model = adapter.load(
        "candidate"
    )

    prediction = adapter.predict(
        model,
        "features",
    )

    assert prediction == "prediction"


def test_load_model_artifact_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.gatekeeper.plugins.load_plugin_object",
        lambda reference: FakeModelArtifactResolver,
    )

    resolver = load_model_artifact_resolver(
        "fake.module:FakeModelArtifactResolver"
    )

    resolved = resolver.resolve(
        "candidate"
    )

    assert resolved == "/tmp/candidate.pt"


def test_rejects_invalid_golden_set_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.gatekeeper.plugins.load_plugin_object",
        lambda reference: InvalidAdapter,
    )

    with pytest.raises(
        TypeError,
        match="GoldenSetAdapter",
    ):
        load_golden_set_adapter(
            "fake.module:InvalidAdapter"
        )


def test_rejects_invalid_model_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.gatekeeper.plugins.load_plugin_object",
        lambda reference: InvalidAdapter,
    )

    with pytest.raises(
        TypeError,
        match="ModelAdapter",
    ):
        load_model_adapter(
            "fake.module:InvalidAdapter"
        )


def test_rejects_invalid_model_artifact_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sentinel.gatekeeper.plugins.load_plugin_object",
        lambda reference: InvalidAdapter,
    )

    with pytest.raises(
        TypeError,
        match="ModelArtifactResolver",
    ):
        load_model_artifact_resolver(
            "fake.module:InvalidAdapter"
        )