from pathlib import Path
from typing import Any

import torch
from torch import Tensor


class TorchScriptArgmaxModelAdapter:
    """Run argmax classification with a TorchScript model."""

    def load(
        self,
        model_reference: str,
    ) -> Any:
        """Load one TorchScript model from a local artifact."""

        model_path = Path(
            model_reference
        )

        if not model_path.is_file():
            raise FileNotFoundError(
                "TorchScript model was not found: "
                f"{model_path}"
            )

        model = torch.jit.load(
            str(model_path),
            map_location="cpu",
        )

        model.eval()

        return model

    def predict(
        self,
        model: Any,
        features: Any,
    ) -> int:
        """Return the highest-logit class index."""

        if not isinstance(
            features,
            Tensor,
        ):
            raise TypeError(
                "TorchScript classifier expects Tensor features."
            )

        if not callable(model):
            raise TypeError(
                "Loaded TorchScript model must be callable."
            )

        with torch.inference_mode():
            logits = model(
                features.to("cpu")
            )

        if not isinstance(
            logits,
            Tensor,
        ):
            raise TypeError(
                "TorchScript classifier must return a Tensor."
            )

        if (
            logits.ndim != 2
            or logits.shape[0] != 1
        ):
            raise ValueError(
                "TorchScript classifier must return "
                "one two-dimensional logits batch."
            )

        return int(
            logits.argmax(
                dim=1
            ).item()
        )