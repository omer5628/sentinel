import pytest

from sentinel.gatekeeper.metrics import (
    accuracy_metric,
    get_metric,
    macro_f1_metric,
    rmse_metric,
)


def test_accuracy_metric() -> None:
    score = accuracy_metric(
        expected_labels=[0, 1, 2, 3],
        predicted_labels=[0, 1, 0, 3],
    )

    assert score == pytest.approx(0.75)


def test_macro_f1_perfect_predictions() -> None:
    score = macro_f1_metric(
        expected_labels=[0, 1, 2],
        predicted_labels=[0, 1, 2],
    )

    assert score == pytest.approx(1.0)


def test_rmse_metric() -> None:
    score = rmse_metric(
        expected_labels=[1.0, 2.0, 3.0],
        predicted_labels=[1.0, 2.0, 4.0],
    )

    assert score == pytest.approx(
        (1.0 / 3.0) ** 0.5
    )


def test_get_metric_returns_accuracy() -> None:
    metric = get_metric(
        "accuracy"
    )

    assert metric is accuracy_metric


def test_get_metric_is_case_insensitive() -> None:
    metric = get_metric(
        "F1_MACRO"
    )

    assert metric is macro_f1_metric


def test_get_metric_rejects_unknown_metric() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported evaluation metric",
    ):
        get_metric(
            "unknown_metric"
        )


def test_rmse_rejects_non_numeric_values() -> None:
    with pytest.raises(
        ValueError,
        match="requires numeric",
    ):
        rmse_metric(
            expected_labels=["cat"],
            predicted_labels=["dog"],
        )