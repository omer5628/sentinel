import pandas as pd
import pytest

from sentinel.adapters.mnist import (
    exclude_training_holdout_rows,
)


def test_excludes_mnist_holdout_rows() -> None:
    dataframe = pd.DataFrame(
        {
            "label": [0, 1, 2, 3, 4],
            "pixel_0": [10, 20, 30, 40, 50],
        }
    )

    result = exclude_training_holdout_rows(
        dataframe=dataframe,
        holdout_ids=frozenset(
            {
                1,
                3,
            }
        ),
    )

    assert len(result) == 3

    assert result["label"].tolist() == [
        0,
        2,
        4,
    ]


def test_empty_holdout_keeps_all_rows() -> None:
    dataframe = pd.DataFrame(
        {
            "label": [0, 1],
        }
    )

    result = exclude_training_holdout_rows(
        dataframe=dataframe,
        holdout_ids=frozenset(),
    )

    assert len(result) == 2


def test_rejects_non_integer_mnist_holdout_id() -> None:
    dataframe = pd.DataFrame(
        {
            "label": [0, 1],
        }
    )

    with pytest.raises(
        ValueError,
        match="integer source indices",
    ):
        exclude_training_holdout_rows(
            dataframe=dataframe,
            holdout_ids=frozenset(
                {
                    "image-1",
                }
            ),
        )


def test_rejects_missing_source_index() -> None:
    dataframe = pd.DataFrame(
        {
            "label": [0, 1],
        }
    )

    with pytest.raises(
        ValueError,
        match="were not found",
    ):
        exclude_training_holdout_rows(
            dataframe=dataframe,
            holdout_ids=frozenset(
                {
                    999,
                }
            ),
        )