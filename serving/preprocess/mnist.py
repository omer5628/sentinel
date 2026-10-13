"""MNIST-specific ClearML Serving preprocessing adapter.

This file is a source template. The promotion workflow must replace the
__SENTINEL_MODEL_VERSION__ marker with the candidate's registered version
before supplying this file to ``clearml-serving model add --preprocess``.
Do not deploy the unrendered template.
"""

from typing import Any

import numpy as np


IMAGE_CHANNELS = 1
IMAGE_HEIGHT = 28
IMAGE_WIDTH = 28
EXPECTED_SHAPE = (IMAGE_CHANNELS, IMAGE_HEIGHT, IMAGE_WIDTH)
BATCHED_SHAPE = (1, IMAGE_CHANNELS, IMAGE_HEIGHT, IMAGE_WIDTH)
MODEL_VERSION = "__SENTINEL_MODEL_VERSION__"


class Preprocess:
    """Convert MNIST inputs and Triton logits to the Sentinel API contract."""

    def preprocess(
        self,
        body: bytes | dict,
        state: dict,
        collect_custom_statistics_fn: Any = None,
    ) -> np.ndarray:
        """Prepare a single float32 MNIST image for Triton inference."""

        del state, collect_custom_statistics_fn

        if not isinstance(body, dict):
            raise ValueError("The request body must be a JSON object.")

        pixels = body.get("pixels")
        if pixels is None:
            raise ValueError("The request body must contain a 'pixels' field.")

        input_array = np.asarray(pixels, dtype=np.float32)

        if input_array.shape in (
            (IMAGE_HEIGHT, IMAGE_WIDTH),
            EXPECTED_SHAPE,
        ):
            input_array = input_array.reshape(BATCHED_SHAPE)
        elif input_array.shape != BATCHED_SHAPE:
            raise ValueError(
                "Invalid pixel shape: expected (28, 28), "
                "(1, 28, 28), or (1, 1, 28, 28); "
                f"received {input_array.shape}."
            )

        if not np.isfinite(input_array).all():
            raise ValueError("The input contains non-finite values.")

        return np.ascontiguousarray(input_array, dtype=np.float32)

    def postprocess(
        self,
        data: Any,
        state: dict,
        collect_custom_statistics_fn: Any = None,
    ) -> dict[str, Any]:
        """Convert ten Triton logits to a prediction and model version."""

        del state, collect_custom_statistics_fn

        if MODEL_VERSION == "__SENTINEL_" + "MODEL_VERSION__":
            raise RuntimeError(
                "The preprocessing template needs a model version "
                "before deployment."
            )

        if not isinstance(data, np.ndarray):
            raise RuntimeError("The inference engine returned an invalid result.")

        logits = np.asarray(data, dtype=np.float32).reshape(-1)
        if logits.size != 10:
            raise RuntimeError(
                f"Invalid model output size: expected 10, received {logits.size}."
            )

        if not np.isfinite(logits).all():
            raise RuntimeError("The model output contains non-finite values.")

        predicted_class = int(np.argmax(logits))
        shifted_logits = logits - np.max(logits)
        exponentials = np.exp(shifted_logits)
        probabilities = exponentials / np.sum(exponentials)

        return {
            "predicted_class": predicted_class,
            "confidence": float(probabilities[predicted_class]),
            "model_version": MODEL_VERSION,
            "logits": logits.tolist(),
        }
