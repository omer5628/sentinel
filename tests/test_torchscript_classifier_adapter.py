from typing import Any, cast

import pytest
import torch
from torch import nn

from sentinel.adapters.torchscript_classifier import (
    TorchScriptArgmaxModelAdapter,
)


class ConstantClassifier(nn.Module):
    """Return deterministic logits for adapter tests."""

    def forward(
        self,
        inputs: torch.Tensor,
    ) -> torch.Tensor:
        batch_size = inputs.shape[0]

        logits = torch.zeros(
            (
                batch_size,
                10,
            )
        )

        logits[:, 4] = 1.0

        return logits


def test_torchscript_adapter_predicts_argmax(
    tmp_path,
) -> None:
    model = ConstantClassifier()

    example_input = torch.zeros(
        (
            1,
            1,
            28,
            28,
        )
    )

    traced_model = cast(
        Any,
        torch.jit.trace(
            model,
            example_input,
        ),
    )

    model_path = (
        tmp_path / "model.pt"
    )

    traced_model.save(
        str(model_path)
    )

    adapter = (
        TorchScriptArgmaxModelAdapter()
    )

    loaded_model = adapter.load(
        str(model_path)
    )

    prediction = adapter.predict(
        loaded_model,
        example_input,
    )

    assert prediction == 4


def test_torchscript_adapter_rejects_missing_model(
    tmp_path,
) -> None:
    adapter = (
        TorchScriptArgmaxModelAdapter()
    )

    with pytest.raises(
        FileNotFoundError,
    ):
        adapter.load(
            str(
                tmp_path / "missing.pt"
            )
        )


def test_torchscript_adapter_rejects_non_tensor_features() -> None:
    adapter = (
        TorchScriptArgmaxModelAdapter()
    )

    with pytest.raises(
        TypeError,
        match="Tensor features",
    ):
        adapter.predict(
            model=lambda value: value,
            features="invalid",
        )