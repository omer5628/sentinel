from datetime import datetime, timezone
from typing import Any

import pytest

from sentinel.retraining.human_data import (
    load_human_labeled_dataset,
)


class FakeCursor:
    """Minimal PostgreSQL cursor used by unit tests."""

    def __init__(
        self,
        rows: list[tuple[Any, Any]],
    ) -> None:
        self._rows = rows

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

    def fetchall(
        self,
    ) -> list[tuple[Any, Any]]:
        return self._rows


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


def test_loads_human_labeled_dataset() -> None:
    cutoff = datetime(
        2026,
        9,
        16,
        8,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (
                [
                    [
                        [
                            [0.1, 0.2],
                            [0.3, 0.4],
                        ]
                    ]
                ],
                "0",
            ),
            (
                [
                    [
                        [
                            [0.5, 0.6],
                            [0.7, 0.8],
                        ]
                    ]
                ],
                "1",
            ),
        ]
    )

    dataset = load_human_labeled_dataset(
        FakeConnection(cursor),
        cutoff=cutoff,
        discard_label="Discard",
        expected_sample_shape=(1, 2, 2),
        label_to_index={
            "0": 0,
            "1": 1,
        },
    )

    images, labels = dataset.tensors

    assert images.shape == (
        2,
        1,
        2,
        2,
    )

    assert labels.tolist() == [
        0,
        1,
    ]


def test_loader_uses_same_retraining_cutoff_filter() -> None:
    cutoff = datetime(
        2026,
        9,
        16,
        8,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        []
    )

    load_human_labeled_dataset(
        FakeConnection(cursor),
        cutoff=cutoff,
        discard_label="Discard",
        expected_sample_shape=(1, 2, 2),
        label_to_index={
            "0": 0,
        },
    )

    query, params = cursor.executed[0]

    assert "label <> %s" in query
    assert "labeled_at <= %s" in query

    assert params == (
        "Discard",
        cutoff,
    )


def test_loader_rejects_unknown_label() -> None:
    cutoff = datetime(
        2026,
        9,
        16,
        8,
        0,
        tzinfo=timezone.utc,
    )

    cursor = FakeCursor(
        [
            (
                [
                    [
                        [
                            [0.1, 0.2],
                            [0.3, 0.4],
                        ]
                    ]
                ],
                "unknown",
            )
        ]
    )

    with pytest.raises(
        ValueError,
        match="unknown label",
    ):
        load_human_labeled_dataset(
            FakeConnection(cursor),
            cutoff=cutoff,
            discard_label="Discard",
            expected_sample_shape=(1, 2, 2),
            label_to_index={
                "0": 0,
            },
        )


def test_empty_human_dataset_preserves_expected_shape() -> None:
    cutoff = datetime(
        2026,
        9,
        16,
        8,
        0,
        tzinfo=timezone.utc,
    )

    dataset = load_human_labeled_dataset(
        FakeConnection(
            FakeCursor([])
        ),
        cutoff=cutoff,
        discard_label="Discard",
        expected_sample_shape=(1, 2, 2),
        label_to_index={
            "0": 0,
        },
    )

    images, labels = dataset.tensors

    assert images.shape == (
        0,
        1,
        2,
        2,
    )

    assert labels.shape == (
        0,
    )
