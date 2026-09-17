import os
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import great_expectations as gx
import pandas as pd
from great_expectations.expectations.core.expect_column_kl_divergence_to_be_less_than import (
    ExpectColumnKLDivergenceToBeLessThan,
)
from great_expectations.expectations.core.expect_column_values_to_not_be_null import (
    ExpectColumnValuesToNotBeNull,
)

from sentinel.retraining.fetch_data import (
    DatabaseConfig,
    DatabaseConnection,
    create_postgres_connection,
)


DistributionStatus = Literal[
    "passed",
    "failed",
    "skipped_no_baseline",
]


@dataclass(frozen=True)
class TrainingDataValidationConfig:
    """Configuration for the retraining data-quality gate."""

    pipeline_name: str
    cutoff: datetime
    discard_label: str
    max_null_fraction: float
    max_label_kl_divergence: float

    @classmethod
    def from_environment(
        cls,
    ) -> "TrainingDataValidationConfig":
        """Load validation configuration from environment variables."""

        cutoff_text = _required_environment_variable(
            "RETRAINING_CUTOFF"
        )

        cutoff = datetime.fromisoformat(
            cutoff_text.replace(
                "Z",
                "+00:00",
            )
        )

        config = cls(
            pipeline_name=_required_environment_variable(
                "RETRAINING_PIPELINE_NAME"
            ),
            cutoff=cutoff,
            discard_label=_required_environment_variable(
                "RETRAINING_DISCARD_LABEL"
            ),
            max_null_fraction=float(
                _required_environment_variable(
                    "RETRAINING_MAX_NULL_FRACTION"
                )
            ),
            max_label_kl_divergence=float(
                _required_environment_variable(
                    "RETRAINING_MAX_LABEL_KL_DIVERGENCE"
                )
            ),
        )

        config.validate()

        return config

    def validate(self) -> None:
        """Validate training-data validation configuration."""

        if not self.pipeline_name.strip():
            raise ValueError(
                "pipeline_name must not be empty."
            )

        if self.cutoff.tzinfo is None:
            raise ValueError(
                "cutoff must include timezone information."
            )

        if not self.discard_label.strip():
            raise ValueError(
                "discard_label must not be empty."
            )

        if not 0.0 <= self.max_null_fraction < 1.0:
            raise ValueError(
                "max_null_fraction must be between 0 and 1."
            )

        if self.max_label_kl_divergence <= 0.0:
            raise ValueError(
                "max_label_kl_divergence must be greater than zero."
            )


@dataclass(frozen=True)
class TrainingDataValidationResult:
    """Result of the retraining data-quality gate."""

    current_rows: int
    baseline_rows: int
    last_successful_cutoff: datetime | None
    max_observed_null_fraction: float
    null_check_passed: bool
    label_distribution_status: DistributionStatus

    @property
    def should_train(self) -> bool:
        """Return whether training may continue."""

        return (
            self.null_check_passed
            and self.label_distribution_status
            != "failed"
        )


def _required_environment_variable(
    name: str,
) -> str:
    """Read one required environment variable."""

    value = os.getenv(
        name
    )

    if value is None or not value.strip():
        raise RuntimeError(
            f"Required environment variable '{name}' is missing."
        )

    return value.strip()


def _fetch_last_successful_cutoff(
    cursor: Any,
    pipeline_name: str,
) -> datetime | None:
    """Read the previous successful retraining checkpoint."""

    cursor.execute(
        """
        SELECT last_successful_cutoff
        FROM retraining_state
        WHERE pipeline_name = %s
        """,
        (
            pipeline_name,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        return None

    cutoff = row[0]

    if not isinstance(
        cutoff,
        datetime,
    ):
        raise RuntimeError(
            "PostgreSQL returned an invalid retraining checkpoint."
        )

    return cutoff


def _fetch_current_rows(
    cursor: Any,
    *,
    discard_label: str,
    cutoff: datetime,
) -> list[tuple[Any, Any]]:
    """Fetch the point-in-time dataset used for validation."""

    cursor.execute(
        """
        SELECT vector, label
        FROM feature_log
        WHERE label IS NOT NULL
          AND label <> %s
          AND labeled_at IS NOT NULL
          AND timestamp <= labeled_at
          AND labeled_at <= %s
        ORDER BY labeled_at ASC, event_id ASC
        """,
        (
            discard_label,
            cutoff,
        ),
    )

    return list(
        cursor.fetchall()
    )


def _fetch_baseline_labels(
    cursor: Any,
    *,
    discard_label: str,
    cutoff: datetime,
) -> list[Any]:
    """Fetch labels from the previous successful training snapshot."""

    cursor.execute(
        """
        SELECT label
        FROM feature_log
        WHERE label IS NOT NULL
          AND label <> %s
          AND labeled_at IS NOT NULL
          AND timestamp <= labeled_at
          AND labeled_at <= %s
        ORDER BY labeled_at ASC, event_id ASC
        """,
        (
            discard_label,
            cutoff,
        ),
    )

    return [
        row[0]
        for row in cursor.fetchall()
    ]


def _normalize_label(
    value: Any,
) -> str | None:
    """Normalize one label for distribution comparison."""

    if value is None:
        return None

    return str(
        value
    ).strip()


def _create_validation_batch(
    dataframe: pd.DataFrame,
) -> Any:
    """Create an in-memory Great Expectations batch."""

    os.environ.setdefault(
        "GX_ANALYTICS_ENABLED",
        "false",
    )

    context = gx.get_context(
        mode="ephemeral"
    )

    data_source = (
        context.data_sources.add_pandas(
            "sentinel-retraining-validation"
        )
    )

    data_asset = (
        data_source.add_dataframe_asset(
            name="training-data"
        )
    )

    batch_definition = (
        data_asset.add_batch_definition_whole_dataframe(
            "training-data-batch"
        )
    )

    return batch_definition.get_batch(
        batch_parameters={
            "dataframe": dataframe,
        }
    )


def _validation_succeeded(
    result: Any,
) -> bool:
    """Read the success flag from a GX validation result."""

    success = getattr(
        result,
        "success",
        None,
    )

    if success is not None:
        return bool(
            success
        )

    try:
        return bool(
            result["success"]
        )
    except (
        KeyError,
        TypeError,
    ):
        return False


def _calculate_null_fractions(
    rows: list[tuple[Any, Any]],
) -> dict[str, float]:
    """Calculate null fractions for fields consumed by training."""

    if not rows:
        raise ValueError(
            "Training validation dataset is empty."
        )

    row_count = len(
        rows
    )

    vector_null_count = sum(
        1
        for vector, _ in rows
        if vector is None
    )

    label_null_count = sum(
        1
        for _, label in rows
        if label is None
    )

    return {
        "vector": (
            vector_null_count
            / row_count
        ),
        "label": (
            label_null_count
            / row_count
        ),
    }


def _evaluate_nulls(
    rows: list[tuple[Any, Any]],
    dataframe: pd.DataFrame,
    *,
    max_null_fraction: float,
) -> tuple[
    bool,
    float,
]:
    """Validate null rates for fields consumed by training."""

    null_fractions = (
        _calculate_null_fractions(
            rows
        )
    )

    max_observed_null_fraction = max(
        null_fractions.values()
    )

    strict_null_check_passed = all(
        null_fraction
        < max_null_fraction
        for null_fraction
        in null_fractions.values()
    )

    batch = _create_validation_batch(
        dataframe
    )

    minimum_non_null_fraction = (
        1.0
        - max_null_fraction
    )

    gx_results: list[bool] = []

    for column in (
        "vector",
        "label",
    ):
        expectation = (
            ExpectColumnValuesToNotBeNull(
                column=column,
                mostly=minimum_non_null_fraction,
            )
        )

        result = batch.validate(
            expectation
        )

        gx_results.append(
            _validation_succeeded(
                result
            )
        )

    return (
        strict_null_check_passed
        and all(
            gx_results
        ),
        max_observed_null_fraction,
    )


def _build_label_partition(
    labels: list[Any],
) -> dict[str, list[Any]]:
    """Build a categorical reference distribution for GX."""

    normalized_labels = [
        normalized
        for value in labels
        if (
            normalized := _normalize_label(
                value
            )
        )
        is not None
    ]

    if not normalized_labels:
        raise ValueError(
            "Baseline label distribution is empty."
        )

    counts = Counter(
        normalized_labels
    )

    total = sum(
        counts.values()
    )

    values = sorted(
        counts
    )

    weights = [
        counts[value]
        / total
        for value in values
    ]

    return {
        "values": values,
        "weights": weights,
    }


def _evaluate_label_distribution(
    current_rows: list[tuple[Any, Any]],
    *,
    baseline_labels: list[Any],
    threshold: float,
) -> bool:
    """Compare current labels with the previous successful run."""

    partition = _build_label_partition(
        baseline_labels
    )

    current_labels = [
        _normalize_label(
            label
        )
        for _, label in current_rows
    ]

    dataframe = pd.DataFrame(
        {
            "label": current_labels,
        }
    )

    batch = _create_validation_batch(
        dataframe
    )

    expectation = (
        ExpectColumnKLDivergenceToBeLessThan(
            column="label",
            partition_object=partition,
            threshold=threshold,
        )
    )

    result = batch.validate(
        expectation
    )

    return _validation_succeeded(
        result
    )


def validate_training_data(
    connection: DatabaseConnection,
    config: TrainingDataValidationConfig,
) -> TrainingDataValidationResult:
    """Validate the current point-in-time retraining dataset."""

    config.validate()

    with connection.cursor() as cursor:
        last_successful_cutoff = (
            _fetch_last_successful_cutoff(
                cursor,
                config.pipeline_name,
            )
        )

        current_rows = (
            _fetch_current_rows(
                cursor,
                discard_label=config.discard_label,
                cutoff=config.cutoff,
            )
        )

        baseline_labels: list[Any] = []

        if last_successful_cutoff is not None:
            baseline_labels = (
                _fetch_baseline_labels(
                    cursor,
                    discard_label=(
                        config.discard_label
                    ),
                    cutoff=(
                        last_successful_cutoff
                    ),
                )
            )

    dataframe = pd.DataFrame(
        current_rows,
        columns=[
            "vector",
            "label",
        ],
    )

    (
        null_check_passed,
        max_observed_null_fraction,
    ) = _evaluate_nulls(
        current_rows,
        dataframe,
        max_null_fraction=(
            config.max_null_fraction
        ),
    )

    distribution_status: DistributionStatus

    if last_successful_cutoff is None:
        distribution_status = (
            "skipped_no_baseline"
        )

    elif not baseline_labels:
        distribution_status = "failed"

    else:
        distribution_passed = (
            _evaluate_label_distribution(
                current_rows,
                baseline_labels=(
                    baseline_labels
                ),
                threshold=(
                    config.max_label_kl_divergence
                ),
            )
        )

        distribution_status = (
            "passed"
            if distribution_passed
            else "failed"
        )

    return TrainingDataValidationResult(
        current_rows=len(
            current_rows
        ),
        baseline_rows=len(
            baseline_labels
        ),
        last_successful_cutoff=(
            last_successful_cutoff
        ),
        max_observed_null_fraction=(
            max_observed_null_fraction
        ),
        null_check_passed=(
            null_check_passed
        ),
        label_distribution_status=(
            distribution_status
        ),
    )


def _print_result(
    result: TrainingDataValidationResult,
    config: TrainingDataValidationConfig,
) -> None:
    """Print machine-readable validation output."""

    previous_cutoff = ""

    if result.last_successful_cutoff is not None:
        previous_cutoff = (
            result.last_successful_cutoff.isoformat()
        )

    validation_status = (
        "passed"
        if result.should_train
        else "blocked"
    )

    print(
        f"validation_status={validation_status}"
    )
    print(
        f"validation_rows={result.current_rows}"
    )
    print(
        f"baseline_rows={result.baseline_rows}"
    )
    print(
        "last_successful_cutoff="
        f"{previous_cutoff}"
    )
    print(
        "max_observed_null_fraction="
        f"{result.max_observed_null_fraction:.6f}"
    )
    print(
        "max_allowed_null_fraction="
        f"{config.max_null_fraction:.6f}"
    )
    print(
        "null_check="
        f"{'passed' if result.null_check_passed else 'failed'}"
    )
    print(
        "label_distribution_check="
        f"{result.label_distribution_status}"
    )
    print(
        "max_label_kl_divergence="
        f"{config.max_label_kl_divergence:.6f}"
    )


def main() -> int:
    """Run the retraining data-quality gate."""

    database_config = (
        DatabaseConfig.from_environment()
    )

    validation_config = (
        TrainingDataValidationConfig.from_environment()
    )

    connection = create_postgres_connection(
        database_config
    )

    try:
        result = validate_training_data(
            connection,
            validation_config,
        )
    finally:
        connection.close()

    _print_result(
        result,
        validation_config,
    )

    if not result.should_train:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )