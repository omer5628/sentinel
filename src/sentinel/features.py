
"""Backward-compatible preprocessing interface for existing consumers."""

from torch import Tensor

from sentinel.adapters.mnist_preprocessing import (
    MNIST_IMAGE_HEIGHT,
    MNIST_IMAGE_WIDTH,
    MNISTImagePreprocessor,
)


# Preserve existing constants for backward compatibility.
IMAGE_WIDTH = MNIST_IMAGE_WIDTH
IMAGE_HEIGHT = MNIST_IMAGE_HEIGHT


_mnist_preprocessor = MNISTImagePreprocessor()


def preprocess_image(raw_bytes: bytes) -> Tensor:
    """Preprocess an image using the existing MNIST adapter.

    This compatibility function preserves the current behavior
    until consumers are migrated to configurable adapters.
    """
    return _mnist_preprocessor(raw_bytes)
