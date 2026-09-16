from datetime import datetime, timezone
from omegaconf import OmegaConf
import pytest
import torch
from torch.utils.data import TensorDataset

from sentinel.train import (
    combine_tensor_datasets,
    get_retraining_cutoff_from_environment,
    apply_retraining_runtime_config,
)


def test_retraining_cutoff_is_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "RETRAINING_CUTOFF",
        raising=False,
    )

    assert (
        get_retraining_cutoff_from_environment()
        is None
    )


def test_retraining_cutoff_is_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RETRAINING_CUTOFF",
        "2026-09-16T08:00:00+00:00",
    )

    cutoff = (
        get_retraining_cutoff_from_environment()
    )

    assert cutoff == datetime(
        2026,
        9,
        16,
        8,
        0,
        tzinfo=timezone.utc,
    )


def test_retraining_cutoff_requires_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RETRAINING_CUTOFF",
        "2026-09-16T08:00:00",
    )

    with pytest.raises(
        ValueError,
        match="timezone",
    ):
        get_retraining_cutoff_from_environment()


def test_combines_base_and_human_datasets() -> None:
    base_dataset = TensorDataset(
        torch.tensor(
            [
                [[[0.1, 0.2], [0.3, 0.4]]],
                [[[0.5, 0.6], [0.7, 0.8]]],
            ],
            dtype=torch.float32,
        ),
        torch.tensor(
            [0, 1],
            dtype=torch.long,
        ),
    )

    human_dataset = TensorDataset(
        torch.tensor(
            [
                [[[0.9, 1.0], [0.8, 0.7]]],
            ],
            dtype=torch.float32,
        ),
        torch.tensor(
            [1],
            dtype=torch.long,
        ),
    )

    combined_dataset = combine_tensor_datasets(
        base_dataset,
        human_dataset,
    )

    images, labels = combined_dataset.tensors

    assert images.shape == (
        3,
        1,
        2,
        2,
    )

    assert labels.tolist() == [
        0,
        1,
        1,
    ]


def test_combining_datasets_rejects_incompatible_shapes() -> None:
    base_dataset = TensorDataset(
        torch.zeros(
            (1, 1, 2, 2),
            dtype=torch.float32,
        ),
        torch.tensor(
            [0],
            dtype=torch.long,
        ),
    )

    human_dataset = TensorDataset(
        torch.zeros(
            (1, 1, 3, 3),
            dtype=torch.float32,
        ),
        torch.tensor(
            [0],
            dtype=torch.long,
        ),
    )

    with pytest.raises(
        ValueError,
        match="incompatible sample shapes",
    ):
        combine_tensor_datasets(
            base_dataset,
            human_dataset,
        )


def test_retraining_runtime_config_is_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "RETRAINING_MODEL_VERSION",
        raising=False,
    )

    cfg = OmegaConf.create(
        {
            "project": {
                "experiment_name": "training-v1",
            },
            "model": {
                "version": "v1",
                "output_path": "artifacts/model-v1.pt",
            },
        }
    )

    updated = apply_retraining_runtime_config(
        cfg
    )

    assert updated.model.version == "v1"
    assert (
        updated.model.output_path
        == "artifacts/model-v1.pt"
    )


def test_retraining_runtime_config_sets_unique_model_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RETRAINING_MODEL_VERSION",
        "retrain-43",
    )

    monkeypatch.setenv(
        "RETRAINING_EXPERIMENT_NAME",
        "retraining-43",
    )

    cfg = OmegaConf.create(
        {
            "project": {
                "experiment_name": "training-v1",
            },
            "model": {
                "version": "v1",
                "output_path": "artifacts/model-v1.pt",
            },
        }
    )

    updated = apply_retraining_runtime_config(
        cfg
    )

    assert (
        updated.model.version
        == "retrain-43"
    )

    assert (
        updated.model.output_path
        == "artifacts/model-retrain-43.pt"
    )

    assert (
        updated.project.experiment_name
        == "retraining-43"
    )
