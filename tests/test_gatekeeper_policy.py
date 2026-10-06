import pytest

from sentinel.gatekeeper.evaluator import (
    ComparisonResult,
    EvaluationResult,
)
from sentinel.gatekeeper.policy import (
    GatePolicy,
    evaluate_gate,
)


def create_comparison(
    current_score: float,
    candidate_score: float,
) -> ComparisonResult:
    """Create a deterministic comparison result for policy tests."""

    return ComparisonResult(
        current=EvaluationResult(
            model_reference="current",
            score=current_score,
            total_samples=100,
        ),
        candidate=EvaluationResult(
            model_reference="candidate",
            score=candidate_score,
            total_samples=100,
        ),
        score_delta=(
            candidate_score
            - current_score
        ),
    )


def test_maximize_policy_accepts_better_candidate() -> None:
    comparison = create_comparison(
        current_score=0.90,
        candidate_score=0.93,
    )

    decision = evaluate_gate(
        comparison=comparison,
        policy=GatePolicy(
            metric_direction="maximize",
        ),
    )

    assert decision.passed is True
    assert decision.regression == pytest.approx(-0.03)


def test_maximize_policy_rejects_excessive_regression() -> None:
    comparison = create_comparison(
        current_score=0.90,
        candidate_score=0.85,
    )

    decision = evaluate_gate(
        comparison=comparison,
        policy=GatePolicy(
            metric_direction="maximize",
            max_regression=0.02,
        ),
    )

    assert decision.passed is False
    assert decision.regression == pytest.approx(0.05)


def test_policy_rejects_candidate_below_absolute_threshold() -> None:
    comparison = create_comparison(
        current_score=0.80,
        candidate_score=0.85,
    )

    decision = evaluate_gate(
        comparison=comparison,
        policy=GatePolicy(
            metric_direction="maximize",
            candidate_score_threshold=0.90,
            threshold_operator="gte",
        ),
    )

    assert decision.passed is False


def test_minimize_policy_accepts_lower_candidate_score() -> None:
    comparison = create_comparison(
        current_score=0.30,
        candidate_score=0.20,
    )

    decision = evaluate_gate(
        comparison=comparison,
        policy=GatePolicy(
            metric_direction="minimize",
        ),
    )

    assert decision.passed is True
    assert decision.regression == pytest.approx(-0.10)


def test_minimize_policy_rejects_higher_candidate_score() -> None:
    comparison = create_comparison(
        current_score=0.20,
        candidate_score=0.30,
    )

    decision = evaluate_gate(
        comparison=comparison,
        policy=GatePolicy(
            metric_direction="minimize",
            max_regression=0.05,
        ),
    )

    assert decision.passed is False


def test_policy_rejects_negative_regression_limit() -> None:
    comparison = create_comparison(
        current_score=0.90,
        candidate_score=0.91,
    )

    with pytest.raises(
        ValueError,
        match="cannot be negative",
    ):
        evaluate_gate(
            comparison=comparison,
            policy=GatePolicy(
                metric_direction="maximize",
                max_regression=-0.01,
            ),
        )