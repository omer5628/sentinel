from datetime import datetime, timezone
from typing import Any

from sentinel.retraining.fetch_data import (
    RetrainingGateConfig,
    evaluate_retraining_gate,
)


class FakeCursor:
    """Minimal PostgreSQL cursor used by unit tests."""

    def __init__(
        self,
        responses: list[Any],
    ) -> None:
        self._responses = iter(
            responses
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
            self._responses
        )


class FakeConnection:
    """Minimal PostgreSQL connection used by unit tests."""

    def __init__(
        self,
        cursor: FakeCursor,
    ) -> None:
        self._cursor = cursor

    def cursor(
        self,
    ) -> FakeCursor:
        return self._cursor


def test_first_retraining_counts_all_eligible_rows_as_new() -> None:
    cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (cutoff,),
            None,
            (27,),
            (27,),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    config = RetrainingGateConfig(
        pipeline_name="sentinel-retraining",
        minimum_new_rows=1000,
        discard_label="Discard",
    )

    result = evaluate_retraining_gate(
        connection,
        config,
    )

    assert result.cutoff == cutoff
    assert result.last_successful_cutoff is None
    assert result.eligible_rows == 27
    assert result.new_rows == 27
    assert result.should_retrain is False


def test_retraining_counts_only_rows_after_checkpoint_as_new() -> None:
    previous_cutoff = datetime(
        2026,
        9,
        14,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (cutoff,),
            (previous_cutoff,),
            (2500,),
            (1000,),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    config = RetrainingGateConfig(
        pipeline_name="sentinel-retraining",
        minimum_new_rows=1000,
        discard_label="Discard",
    )

    result = evaluate_retraining_gate(
        connection,
        config,
    )

    assert result.last_successful_cutoff == previous_cutoff
    assert result.eligible_rows == 2500
    assert result.new_rows == 1000
    assert result.should_retrain is True
    new_rows_query = cursor.executed[3]

    assert "timestamp <= labeled_at" in new_rows_query[0]
    assert "labeled_at > %s" in new_rows_query[0]
    assert "labeled_at <= %s" in new_rows_query[0]


def test_retraining_gate_uses_discard_label_filter() -> None:
    cutoff = datetime(
        2026,
        9,
        15,
        10,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (cutoff,),
            None,
            (27,),
            (27,),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    config = RetrainingGateConfig(
        pipeline_name="sentinel-retraining",
        minimum_new_rows=1000,
        discard_label="Discard",
    )

    evaluate_retraining_gate(
        connection,
        config,
    )

    eligible_query = cursor.executed[2]
    new_rows_query = cursor.executed[3]

    assert "label <> %s" in eligible_query[0]
    assert "timestamp <= labeled_at" in eligible_query[0]
    assert eligible_query[1][0] == "Discard"

    assert "label <> %s" in new_rows_query[0]
    assert "timestamp <= labeled_at" in new_rows_query[0]
    assert new_rows_query[1][0] == "Discard"
