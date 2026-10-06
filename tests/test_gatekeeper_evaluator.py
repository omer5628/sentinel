from collections.abc import Hashable
from typing import Any

import pytest

from sentinel.gatekeeper.contracts import GoldenSample
from sentinel.gatekeeper.evaluator import (
    compare_models,
    evaluate_model,
)
from sentinel.gatekeeper.metrics import (
    accuracy_metric,
)


class FakeModelAdapter:
    """Provide deterministic predictions for gatekeeper tests."""

    def __init__(
        self,
        predictions: dict[
            str,
            dict[Hashable, Hashable],
        ],
    ) -> None:
        self.predictions = predictions

    def load(
        self,
        model_reference: str,
    ) -> str:
        return model_reference

    def predict(
        self,
        model: Any,
        features: Any,
    ) -> Hashable:
        return self.predictions[str(model)][features]


def test_accuracy_metric_returns_expected_score() -> None:
    score = accuracy_metric(
        expected_labels=[0, 1, 2, 3],
        predicted_labels=[0, 1, 0, 3],
    )

    assert score == pytest.approx(0.75)


def test_accuracy_metric_rejects_empty_labels() -> None:
    with pytest.raises(
        ValueError,
        match="cannot be empty",
    ):
        accuracy_metric(
            expected_labels=[],
            predicted_labels=[],
        )


def test_evaluate_model_uses_adapter_predictions() -> None:
    adapter = FakeModelAdapter(
        predictions={
            "current": {
                "a": 0,
                "b": 1,
            },
        }
    )

    samples = [
        GoldenSample(
            features="a",
            label=0,
        ),
        GoldenSample(
            features="b",
            label=1,
        ),
    ]

    result = evaluate_model(
        model_adapter=adapter,
        model_reference="current",
        samples=samples,
        metric=accuracy_metric,
    )

    assert result.model_reference == "current"
    assert result.score == pytest.approx(1.0)
    assert result.total_samples == 2


def test_compare_models_reports_score_delta() -> None:
    adapter = FakeModelAdapter(
        predictions={
            "current": {
                "a": 0,
                "b": 0,
                "c": 2,
                "d": 0,
            },
            "candidate": {
                "a": 0,
                "b": 1,
                "c": 2,
                "d": 3,
            },
        }
    )

    samples = [
        GoldenSample(
            features="a",
            label=0,
        ),
        GoldenSample(
            features="b",
            label=1,
        ),
        GoldenSample(
            features="c",
            label=2,
        ),
        GoldenSample(
            features="d",
            label=3,
        ),
    ]

    result = compare_models(
        model_adapter=adapter,
        current_model_reference="current",
        candidate_model_reference="candidate",
        samples=samples,
        metric=accuracy_metric,
    )

    assert result.current.score == pytest.approx(0.5)
    assert result.candidate.score == pytest.approx(1.0)
    assert result.score_delta == pytest.approx(0.5)