from typing import Any

import numpy as np


IMAGE_CHANNELS = 1
IMAGE_HEIGHT = 28
IMAGE_WIDTH = 28

EXPECTED_SHAPE = (
    IMAGE_CHANNELS,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
)

BATCHED_SHAPE = (
    1,
    IMAGE_CHANNELS,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
)

MODEL_VERSION = "v1"


class Preprocess:
    """Prepare MNIST requests and format V1 prediction responses."""

    def preprocess(
        self,
        body: bytes | dict,
        state: dict,
        collect_custom_statistics_fn: Any = None,
    ) -> np.ndarray:
        """Convert a JSON request into a batched float32 MNIST tensor."""

        del state
        del collect_custom_statistics_fn

        if not isinstance(body, dict):
            raise ValueError(
                "The request body must be a JSON object."
            )

        pixels = body.get("pixels")

        if pixels is None:
            raise ValueError(
                "The request body must contain a 'pixels' field."
            )

        input_array = np.asarray(
            pixels,
            dtype=np.float32,
        )

        if input_array.shape == (
            IMAGE_HEIGHT,
            IMAGE_WIDTH,
        ):
            input_array = input_array.reshape(
                BATCHED_SHAPE
            )

        elif input_array.shape == EXPECTED_SHAPE:
            input_array = input_array.reshape(
                BATCHED_SHAPE
            )

        elif input_array.shape != BATCHED_SHAPE:
            raise ValueError(
                "Invalid pixel shape: "
                "expected (28, 28), "
                "(1, 28, 28), or "
                "(1, 1, 28, 28), "
                f"received {input_array.shape}."
            )

        if not np.isfinite(input_array).all():
            raise ValueError(
                "The input contains non-finite values."
            )

        return np.ascontiguousarray(
            input_array,
            dtype=np.float32,
        )

    def postprocess(
        self,
        data: Any,
        state: dict,
        collect_custom_statistics_fn: Any = None,
    ) -> dict[str, Any]:
        """Convert Triton logits into a prediction response."""

        del state
        del collect_custom_statistics_fn

        if not isinstance(data, np.ndarray):
            raise RuntimeError(
                "The inference engine returned an invalid result."
            )

        logits = np.asarray(
            data,
            dtype=np.float32,
        ).reshape(-1)

        if logits.size != 10:
            raise RuntimeError(
                "Invalid model output size: "
                f"expected 10, received {logits.size}."
            )

        predicted_class = int(
            np.argmax(logits)
        )

        shifted_logits = (
            logits - np.max(logits)
        )

        exponentials = np.exp(
            shifted_logits
        )

        probabilities = (
            exponentials / np.sum(exponentials)
        )

        return {
            "predicted_class": predicted_class,
            "confidence": float(
                probabilities[predicted_class]
            ),
            "model_version": MODEL_VERSION,
            "logits": logits.tolist(),
        }