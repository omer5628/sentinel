from datetime import datetime, timezone
from typing import Any

from sentinel.retraining.validate_data import (
    TrainingDataValidationConfig,
    validate_training_data,
)


class FakeCursor:
    """Minimal PostgreSQL cursor used by validation tests."""

    def __init__(
        self,
        *,
        fetchone_responses: list[Any],
        fetchall_responses: list[list[Any]],
    ) -> None:
        self._fetchone_responses = iter(
            fetchone_responses
        )

        self._fetchall_responses = iter(
            fetchall_responses
        )

        self.executed: list[
            tuple[
                str,
                tuple[Any, ...],
            ]
        ] = []

    def __enter__(
        self,
    ) -> "FakeCursor":
        return self

    def __exit__(
        self,
        exc_type: Any,
        exc_value: Any,
        traceback: Any,
    ) -> None:
        return None

    def execute(
        self,
        query: str,
        params: tuple[Any, ...] | None = None,
    ) -> None:
        normalized_query = " ".join(
            query.split()
        )

        self.executed.append(
            (
                normalized_query,
                params or (),
            )
        )

    def fetchone(
        self,
    ) -> Any:
        return next(
            self._fetchone_responses
        )

    def fetchall(
        self,
    ) -> list[Any]:
        return next(
            self._fetchall_responses
        )


class FakeConnection:
    """Minimal PostgreSQL connection used by validation tests."""

    def __init__(
        self,
        cursor: FakeCursor,
    ) -> None:
        self._cursor = cursor

    def cursor(
        self,
    ) -> FakeCursor:
        return self._cursor


def _config(
    cutoff: datetime,
) -> TrainingDataValidationConfig:
    return TrainingDataValidationConfig(
        pipeline_name="sentinel-retraining",
        cutoff=cutoff,
        discard_label="Discard",
        max_null_fraction=0.01,
        max_label_kl_divergence=0.1,
    )


def test_first_run_skips_distribution_without_baseline() -> None:
    cutoff = datetime(
        2026,
        9,
        16,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        fetchone_responses=[
            None,
        ],
        fetchall_responses=[
            [
                ([0.1, 0.2], "0"),
                ([0.3, 0.4], "1"),
            ],
        ],
    )

    result = validate_training_data(
        FakeConnection(
            cursor
        ),
        _config(
            cutoff
        ),
    )

    assert result.current_rows == 2
    assert result.baseline_rows == 0
    assert result.null_check_passed is True

    assert (
        result.label_distribution_status
        == "skipped_no_baseline"
    )

    assert result.should_train is True


def test_validation_uses_point_in_time_filters() -> None:
    previous_cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cutoff = datetime(
        2026,
        9,
        16,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        fetchone_responses=[
            (
                previous_cutoff,
            ),
        ],
        fetchall_responses=[
            [
                ([0.1], "0"),
                ([0.2], "1"),
            ],
            [
                ("0",),
                ("1",),
            ],
        ],
    )

    result = validate_training_data(
        FakeConnection(
            cursor
        ),
        _config(
            cutoff
        ),
    )

    assert result.should_train is True

    current_query = cursor.executed[1]
    baseline_query = cursor.executed[2]

    assert "label <> %s" in current_query[0]
    assert "timestamp <= labeled_at" in current_query[0]
    assert "labeled_at <= %s" in current_query[0]

    assert current_query[1] == (
        "Discard",
        cutoff,
    )

    assert "label <> %s" in baseline_query[0]
    assert "timestamp <= labeled_at" in baseline_query[0]
    assert "labeled_at <= %s" in baseline_query[0]

    assert baseline_query[1] == (
        "Discard",
        previous_cutoff,
    )


def test_exactly_one_percent_nulls_is_blocked() -> None:
    cutoff = datetime(
        2026,
        9,
        16,
        10,
        0,
        tzinfo=timezone.utc,
    )

    rows: list[
        tuple[Any, str]
    ] = [
        (
            [float(index)],
            str(
                index % 2
            ),
        )
        for index in range(
            100
        )
    ]

    rows[0] = (
        None,
        "0",
    )

    cursor = FakeCursor(
        fetchone_responses=[
            None,
        ],
        fetchall_responses=[
            rows,
        ],
    )

    result = validate_training_data(
        FakeConnection(
            cursor
        ),
        _config(
            cutoff
        ),
    )

    assert (
        result.max_observed_null_fraction
        == 0.01
    )

    assert result.null_check_passed is False
    assert result.should_train is False


def test_similar_label_distribution_passes() -> None:
    previous_cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cutoff = datetime(
        2026,
        9,
        16,
        10,
        0,
        tzinfo=timezone.utc,
    )

    current_rows = [
        (
            [float(index)],
            "0" if index < 50 else "1",
        )
        for index in range(
            100
        )
    ]

    baseline_rows = [
        (
            "0" if index < 50 else "1",
        )
        for index in range(
            100
        )
    ]

    cursor = FakeCursor(
        fetchone_responses=[
            (
                previous_cutoff,
            ),
        ],
        fetchall_responses=[
            current_rows,
            baseline_rows,
        ],
    )

    result = validate_training_data(
        FakeConnection(
            cursor
        ),
        _config(
            cutoff
        ),
    )

    assert (
        result.label_distribution_status
        == "passed"
    )

    assert result.should_train is True


def test_shifted_label_distribution_is_blocked() -> None:
    previous_cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cutoff = datetime(
        2026,
        9,
        16,
        10,
        0,
        tzinfo=timezone.utc,
    )

    current_rows = [
        (
            [float(index)],
            "0" if index < 90 else "1",
        )
        for index in range(
            100
        )
    ]

    baseline_rows = [
        (
            "0" if index < 50 else "1",
        )
        for index in range(
            100
        )
    ]

    cursor = FakeCursor(
        fetchone_responses=[
            (
                previous_cutoff,
            ),
        ],
        fetchall_responses=[
            current_rows,
            baseline_rows,
        ],
    )

    result = validate_training_data(
        FakeConnection(
            cursor
        ),
        _config(
            cutoff
        ),
    )

    assert (
        result.label_distribution_status
        == "failed"
    )

    assert result.should_train is False


def test_checkpoint_without_baseline_data_fails_closed() -> None:
    previous_cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cutoff = datetime(
        2026,
        9,
        16,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        fetchone_responses=[
            (
                previous_cutoff,
            ),
        ],
        fetchall_responses=[
            [
                ([0.1], "0"),
                ([0.2], "1"),
            ],
            [],
        ],
    )

    result = validate_training_data(
        FakeConnection(
            cursor
        ),
        _config(
            cutoff
        ),
    )

    assert (
        result.label_distribution_status
        == "failed"
    )

    assert result.should_train is False