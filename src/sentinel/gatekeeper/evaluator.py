import math
from collections.abc import (
    Hashable,
    Sequence,
)
from dataclasses import dataclass

from sentinel.gatekeeper.contracts import (
    GoldenSample,
    ModelAdapter,
)
from sentinel.gatekeeper.metrics import (
    MetricFunction,
)


@dataclass(frozen=True)
class EvaluationResult:
    """Represent the evaluation score of one model."""

    model_reference: str
    score: float
    total_samples: int


@dataclass(frozen=True)
class ComparisonResult:
    """Represent the evaluation of current and candidate models."""

    current: EvaluationResult
    candidate: EvaluationResult
    score_delta: float


def evaluate_model(
    model_adapter: ModelAdapter,
    model_reference: str,
    samples: Sequence[GoldenSample],
    metric: MetricFunction,
) -> EvaluationResult:
    """Evaluate one model against a fixed golden dataset."""

    if not samples:
        raise ValueError(
            "Golden dataset cannot be empty."
        )

    model = model_adapter.load(
        model_reference
    )

    expected_labels: list[Hashable] = []
    predicted_labels: list[Hashable] = []

    for sample in samples:
        prediction = model_adapter.predict(
            model,
            sample.features,
        )

        expected_labels.append(
            sample.label
        )

        predicted_labels.append(
            prediction
        )

    score = float(
        metric(
            expected_labels,
            predicted_labels,
        )
    )

    if not math.isfinite(score):
        raise ValueError(
            "Evaluation metric returned a non-finite score."
        )

    return EvaluationResult(
        model_reference=model_reference,
        score=score,
        total_samples=len(samples),
    )


def compare_models(
    model_adapter: ModelAdapter,
    current_model_reference: str,
    candidate_model_reference: str,
    samples: Sequence[GoldenSample],
    metric: MetricFunction,
) -> ComparisonResult:
    """Evaluate current and candidate models on the same dataset."""

    current_result = evaluate_model(
        model_adapter=model_adapter,
        model_reference=current_model_reference,
        samples=samples,
        metric=metric,
    )

    candidate_result = evaluate_model(
        model_adapter=model_adapter,
        model_reference=candidate_model_reference,
        samples=samples,
        metric=metric,
    )

    return ComparisonResult(
        current=current_result,
        candidate=candidate_result,
        score_delta=(
            candidate_result.score
            - current_result.score
        ),
    )