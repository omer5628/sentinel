import math
from collections.abc import (
    Callable,
    Hashable,
    Sequence,
)
from typing import Any, cast


MetricFunction = Callable[
    [Sequence[Hashable], Sequence[Hashable]],
    float,
]


def _validate_metric_inputs(
    expected_labels: Sequence[Hashable],
    predicted_labels: Sequence[Hashable],
) -> None:
    """Validate common metric input requirements."""

    if not expected_labels:
        raise ValueError(
            "Expected labels cannot be empty."
        )

    if len(expected_labels) != len(predicted_labels):
        raise ValueError(
            "Expected and predicted value counts must match."
        )


def _to_float(
    value: Hashable,
) -> float:
    """Convert a generic metric value into a float."""

    try:
        return float(
            cast(Any, value)
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "Metric value must be numeric."
        ) from error


def accuracy_metric(
    expected_labels: Sequence[Hashable],
    predicted_labels: Sequence[Hashable],
) -> float:
    """Calculate classification accuracy."""

    _validate_metric_inputs(
        expected_labels,
        predicted_labels,
    )

    correct_predictions = sum(
        expected == predicted
        for expected, predicted in zip(
            expected_labels,
            predicted_labels,
            strict=True,
        )
    )

    return (
        correct_predictions
        / len(expected_labels)
    )


def macro_f1_metric(
    expected_labels: Sequence[Hashable],
    predicted_labels: Sequence[Hashable],
) -> float:
    """Calculate macro-averaged F1 across all observed classes."""

    _validate_metric_inputs(
        expected_labels,
        predicted_labels,
    )

    classes = set(expected_labels) | set(
        predicted_labels
    )

    f1_scores: list[float] = []

    for class_label in classes:
        true_positive = sum(
            expected == class_label
            and predicted == class_label
            for expected, predicted in zip(
                expected_labels,
                predicted_labels,
                strict=True,
            )
        )

        false_positive = sum(
            expected != class_label
            and predicted == class_label
            for expected, predicted in zip(
                expected_labels,
                predicted_labels,
                strict=True,
            )
        )

        false_negative = sum(
            expected == class_label
            and predicted != class_label
            for expected, predicted in zip(
                expected_labels,
                predicted_labels,
                strict=True,
            )
        )

        precision_denominator = (
            true_positive + false_positive
        )

        recall_denominator = (
            true_positive + false_negative
        )

        precision = (
            true_positive / precision_denominator
            if precision_denominator
            else 0.0
        )

        recall = (
            true_positive / recall_denominator
            if recall_denominator
            else 0.0
        )

        if precision + recall == 0:
            f1_score = 0.0
        else:
            f1_score = (
                2.0
                * precision
                * recall
                / (precision + recall)
            )

        f1_scores.append(
            f1_score
        )

    return (
        sum(f1_scores)
        / len(f1_scores)
    )


def rmse_metric(
    expected_labels: Sequence[Hashable],
    predicted_labels: Sequence[Hashable],
) -> float:
    """Calculate root mean squared error."""

    _validate_metric_inputs(
        expected_labels,
        predicted_labels,
    )

    squared_errors: list[float] = []

    for expected, predicted in zip(
        expected_labels,
        predicted_labels,
        strict=True,
    ):
        try:
            expected_value = _to_float(
                expected
            )

            predicted_value = _to_float(
                predicted
            )
        except ValueError as error:
            raise ValueError(
                "RMSE requires numeric expected and predicted values."
            ) from error

        squared_errors.append(
            (
                expected_value
                - predicted_value
            )
            ** 2
        )

    return math.sqrt(
        sum(squared_errors)
        / len(squared_errors)
    )


_BUILT_IN_METRICS: dict[
    str,
    MetricFunction,
] = {
    "accuracy": accuracy_metric,
    "f1_macro": macro_f1_metric,
    "rmse": rmse_metric,
}


def get_metric(
    metric_name: str,
) -> MetricFunction:
    """Resolve a built-in metric by configuration name."""

    normalized_name = (
        metric_name.strip().lower()
    )

    try:
        return _BUILT_IN_METRICS[
            normalized_name
        ]
    except KeyError as error:
        supported_metrics = ", ".join(
            sorted(_BUILT_IN_METRICS)
        )

        raise ValueError(
            f"Unsupported evaluation metric: {metric_name}. "
            f"Supported metrics: {supported_metrics}."
        ) from error