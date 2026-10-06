from dataclasses import dataclass
from typing import Literal

from sentinel.gatekeeper.evaluator import (
    ComparisonResult,
)


MetricDirection = Literal[
    "maximize",
    "minimize",
]

ThresholdOperator = Literal[
    "gte",
    "lte",
]


@dataclass(frozen=True)
class GatePolicy:
    """Define configurable rules for candidate model promotion."""

    metric_direction: MetricDirection
    max_regression: float = 0.0
    candidate_score_threshold: float | None = None
    threshold_operator: ThresholdOperator = "gte"


@dataclass(frozen=True)
class GateDecision:
    """Represent the final gatekeeper promotion decision."""

    passed: bool
    regression: float
    reason: str


def calculate_regression(
    comparison: ComparisonResult,
    metric_direction: MetricDirection,
) -> float:
    """Calculate candidate regression relative to the current model."""

    if metric_direction == "maximize":
        return (
            comparison.current.score
            - comparison.candidate.score
        )

    if metric_direction == "minimize":
        return (
            comparison.candidate.score
            - comparison.current.score
        )

    raise ValueError(
        f"Unsupported metric direction: {metric_direction}"
    )


def passes_absolute_threshold(
    score: float,
    threshold: float,
    operator: ThresholdOperator,
) -> bool:
    """Evaluate one candidate score against an absolute threshold."""

    if operator == "gte":
        return score >= threshold

    if operator == "lte":
        return score <= threshold

    raise ValueError(
        f"Unsupported threshold operator: {operator}"
    )


def evaluate_gate(
    comparison: ComparisonResult,
    policy: GatePolicy,
) -> GateDecision:
    """Decide whether the candidate model may continue toward promotion."""

    if policy.max_regression < 0:
        raise ValueError(
            "max_regression cannot be negative."
        )

    regression = calculate_regression(
        comparison=comparison,
        metric_direction=policy.metric_direction,
    )

    if regression > policy.max_regression:
        return GateDecision(
            passed=False,
            regression=regression,
            reason=(
                "Candidate regression exceeds the configured limit."
            ),
        )

    if policy.candidate_score_threshold is not None:
        threshold_passed = passes_absolute_threshold(
            score=comparison.candidate.score,
            threshold=policy.candidate_score_threshold,
            operator=policy.threshold_operator,
        )

        if not threshold_passed:
            return GateDecision(
                passed=False,
                regression=regression,
                reason=(
                    "Candidate score does not satisfy the "
                    "configured absolute threshold."
                ),
            )

    return GateDecision(
        passed=True,
        regression=regression,
        reason="Candidate passed all configured gatekeeper rules.",
    )