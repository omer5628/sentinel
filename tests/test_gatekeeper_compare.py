from pathlib import Path
from typing import Any

import pytest
from omegaconf import OmegaConf

from sentinel.gatekeeper import compare
from sentinel.gatekeeper.contracts import (
    GoldenSample,
)


class FakeGoldenSetAdapter:
    """Provide deterministic golden samples."""

    def load(
        self,
        dataset_path: Path,
    ) -> list[GoldenSample]:
        return [
            GoldenSample(
                features=0,
                label=0,
            ),
            GoldenSample(
                features=1,
                label=1,
            ),
        ]


class FakeArtifactResolver:
    """Resolve fake immutable references."""

    def resolve(
        self,
        model_reference: str,
    ) -> str:
        return (
            f"/models/"
            f"{model_reference}.pt"
        )


class ImprovingModelAdapter:
    """Return better predictions for the candidate."""

    def load(
        self,
        model_reference: str,
    ) -> str:
        return model_reference

    def predict(
        self,
        model: Any,
        features: Any,
    ) -> int:
        if "candidate" in str(model):
            return int(
                features
            )

        return 0


class RegressingModelAdapter:
    """Return worse predictions for the candidate."""

    def load(
        self,
        model_reference: str,
    ) -> str:
        return model_reference

    def predict(
        self,
        model: Any,
        features: Any,
    ) -> int:
        if "candidate" in str(model):
            return 0

        return int(
            features
        )


def create_config():
    """Create a valid gatekeeper configuration."""

    return OmegaConf.create(
        {
            "enabled": True,
            "golden_set": {
                "path": "data/golden_set.csv",
                "required_samples": 2,
            },
            "evaluation": {
                "metric": "accuracy",
                "direction": "maximize",
            },
            "adapters": {
                "golden_set": (
                    "fake:GoldenSetAdapter"
                ),
                "model": (
                    "fake:ModelAdapter"
                ),
            },
            "artifacts": {
                "resolver": (
                    "fake:ArtifactResolver"
                ),
            },
            "policy": {
                "max_regression": 0.0,
                "candidate_score_threshold": None,
                "threshold_operator": "gte",
            },
        }
    )


def configure_plugins(
    monkeypatch: pytest.MonkeyPatch,
    model_adapter: Any,
) -> None:
    """Replace configured plugins with test doubles."""

    monkeypatch.setattr(
        compare,
        "load_golden_set_adapter",
        lambda reference: FakeGoldenSetAdapter(),
    )

    monkeypatch.setattr(
        compare,
        "load_model_artifact_resolver",
        lambda reference: FakeArtifactResolver(),
    )

    monkeypatch.setattr(
        compare,
        "load_model_adapter",
        lambda reference: model_adapter,
    )


def test_gatekeeper_passes_improving_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_plugins(
        monkeypatch,
        ImprovingModelAdapter(),
    )

    result = compare.run_gatekeeper(
        cfg=create_config(),
        current_model_reference="current",
        candidate_model_reference="candidate",
    )

    assert result.decision.passed is True
    assert result.comparison.current.score == 0.5
    assert result.comparison.candidate.score == 1.0
    assert result.comparison.score_delta == 0.5


def test_gatekeeper_rejects_regressing_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_plugins(
        monkeypatch,
        RegressingModelAdapter(),
    )

    result = compare.run_gatekeeper(
        cfg=create_config(),
        current_model_reference="current",
        candidate_model_reference="candidate",
    )

    assert result.decision.passed is False
    assert result.comparison.current.score == 1.0
    assert result.comparison.candidate.score == 0.5
    assert result.comparison.score_delta == -0.5


def test_gatekeeper_rejects_same_model_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_plugins(
        monkeypatch,
        ImprovingModelAdapter(),
    )

    with pytest.raises(
        ValueError,
        match=(
            "must be different"
        ),
    ):
        compare.run_gatekeeper(
            cfg=create_config(),
            current_model_reference="same-model",
            candidate_model_reference="same-model",
        )


def test_gatekeeper_rejects_wrong_golden_sample_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_plugins(
        monkeypatch,
        ImprovingModelAdapter(),
    )

    cfg = create_config()

    cfg.golden_set.required_samples = 100

    with pytest.raises(
        ValueError,
        match=(
            "sample count does not match"
        ),
    ):
        compare.run_gatekeeper(
            cfg=cfg,
            current_model_reference="current",
            candidate_model_reference="candidate",
        )


def test_gatekeeper_fails_closed_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_plugins(
        monkeypatch,
        ImprovingModelAdapter(),
    )

    cfg = create_config()

    cfg.enabled = False

    with pytest.raises(
        RuntimeError,
        match="Gatekeeper is disabled",
    ):
        compare.run_gatekeeper(
            cfg=cfg,
            current_model_reference="current",
            candidate_model_reference="candidate",
        )
