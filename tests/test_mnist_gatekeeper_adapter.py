import pandas as pd
import pytest
import torch

from sentinel.adapters.mnist import (
    EXPECTED_PIXEL_COUNT,
    MNISTGoldenSetAdapter,
)


def test_load_mnist_golden_set(
    tmp_path,
) -> None:
    columns = [
        f"pixel_{index}"
        for index in range(
            EXPECTED_PIXEL_COUNT
        )
    ]

    dataframe = pd.DataFrame(
        [
            [3] + [0] * EXPECTED_PIXEL_COUNT,
            [7] + [255] * EXPECTED_PIXEL_COUNT,
        ],
        columns=["label", *columns],
    )

    dataset_path = (
        tmp_path / "golden_set.csv"
    )

    dataframe.to_csv(
        dataset_path,
        index=False,
    )

    adapter = MNISTGoldenSetAdapter()

    samples = adapter.load(
        dataset_path
    )

    assert len(samples) == 2

    assert samples[0].label == 3
    assert samples[1].label == 7

    assert isinstance(
        samples[0].features,
        torch.Tensor,
    )

    assert tuple(
        samples[0].features.shape
    ) == (
        1,
        1,
        28,
        28,
    )

    assert samples[0].features.dtype == (
        torch.float32
    )

    assert float(
        samples[0].features.min()
    ) == pytest.approx(0.0)

    assert float(
        samples[1].features.max()
    ) == pytest.approx(1.0)


def test_rejects_wrong_pixel_count(
    tmp_path,
) -> None:
    dataframe = pd.DataFrame(
        {
            "label": [1],
            "pixel_0": [0],
        }
    )

    dataset_path = (
        tmp_path / "golden_set.csv"
    )

    dataframe.to_csv(
        dataset_path,
        index=False,
    )

    adapter = MNISTGoldenSetAdapter()

    with pytest.raises(
        ValueError,
        match="pixel columns",
    ):
        adapter.load(
            dataset_path
        )