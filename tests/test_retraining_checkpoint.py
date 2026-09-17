from datetime import datetime, timezone
from typing import Any

import pytest

from sentinel.retraining.checkpoint import (
    RetrainingCheckpointConfig,
    update_retraining_checkpoint,
)


class FakeCursor:
    """Minimal PostgreSQL cursor used by checkpoint tests."""

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
    """Minimal writable PostgreSQL connection used by tests."""

    def __init__(
        self,
        cursor: FakeCursor,
    ) -> None:
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(
        self,
    ) -> FakeCursor:
        return self._cursor

    def commit(
        self,
    ) -> None:
        self.committed = True

    def rollback(
        self,
    ) -> None:
        self.rolled_back = True


def test_creates_first_successful_checkpoint() -> None:
    cutoff = datetime(
        2026,
        9,
        17,
        6,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            None,
            (
                cutoff,
            ),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    result = update_retraining_checkpoint(
        connection,
        RetrainingCheckpointConfig(
            pipeline_name="sentinel-retraining",
            cutoff=cutoff,
        ),
    )

    assert result.previous_cutoff is None
    assert result.current_cutoff == cutoff
    assert result.advanced is True

    assert connection.committed is True
    assert connection.rolled_back is False


def test_advances_existing_checkpoint() -> None:
    previous_cutoff = datetime(
        2026,
        9,
        16,
        6,
        0,
        tzinfo=timezone.utc,
    )

    cutoff = datetime(
        2026,
        9,
        17,
        6,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (
                previous_cutoff,
            ),
            (
                cutoff,
            ),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    result = update_retraining_checkpoint(
        connection,
        RetrainingCheckpointConfig(
            pipeline_name="sentinel-retraining",
            cutoff=cutoff,
        ),
    )

    assert result.previous_cutoff == previous_cutoff
    assert result.current_cutoff == cutoff
    assert result.advanced is True

    update_query = cursor.executed[1]

    assert "ON CONFLICT (pipeline_name)" in update_query[0]

    assert (
        "retraining_state.last_successful_cutoff "
        "<= EXCLUDED.last_successful_cutoff"
        in update_query[0]
    )

    assert update_query[1] == (
        "sentinel-retraining",
        cutoff,
    )

    assert connection.committed is True
    assert connection.rolled_back is False


def test_same_checkpoint_is_idempotent() -> None:
    cutoff = datetime(
        2026,
        9,
        17,
        6,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (
                cutoff,
            ),
            (
                cutoff,
            ),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    result = update_retraining_checkpoint(
        connection,
        RetrainingCheckpointConfig(
            pipeline_name="sentinel-retraining",
            cutoff=cutoff,
        ),
    )

    assert result.previous_cutoff == cutoff
    assert result.current_cutoff == cutoff
    assert result.advanced is False

    assert connection.committed is True
    assert connection.rolled_back is False


def test_rejects_checkpoint_rollback() -> None:
    stored_cutoff = datetime(
        2026,
        9,
        17,
        6,
        0,
        tzinfo=timezone.utc,
    )

    older_cutoff = datetime(
        2026,
        9,
        16,
        6,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (
                stored_cutoff,
            ),
        ]
    )

    connection = FakeConnection(
        cursor
    )

    with pytest.raises(
        ValueError,
        match="backwards",
    ):
        update_retraining_checkpoint(
            connection,
            RetrainingCheckpointConfig(
                pipeline_name="sentinel-retraining",
                cutoff=older_cutoff,
            ),
        )

    assert connection.committed is False
    assert connection.rolled_back is True

    assert len(
        cursor.executed
    ) == 1


def test_checkpoint_requires_timezone() -> None:
    config = RetrainingCheckpointConfig(
        pipeline_name="sentinel-retraining",
        cutoff=datetime(
            2026,
            9,
            17,
            6,
            0,
        ),
    )

    with pytest.raises(
        ValueError,
        match="timezone",
    ):
        config.validate()