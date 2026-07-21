from io import BytesIO

import numpy as np
import pytest
import torch
from PIL import Image

from sentinel.features import preprocess_image


def create_test_image_bytes() -> bytes:
    """Create a grayscale PNG image for preprocessing tests."""

    image_array = np.full(
        (28, 28),
        fill_value=255,
        dtype=np.uint8,
    )
    image = Image.fromarray(image_array, mode="L")

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")

    return image_buffer.getvalue()


def test_preprocess_image_returns_expected_tensor() -> None:
    """Verify tensor shape, type, and normalized values."""

    tensor = preprocess_image(create_test_image_bytes())

    assert tensor.shape == (1, 1, 28, 28)
    assert tensor.dtype == torch.float32
    assert torch.all(tensor >= 0.0)
    assert torch.all(tensor <= 1.0)


def test_preprocess_image_rejects_empty_bytes() -> None:
    """Verify that empty image bytes are rejected."""

    with pytest.raises(ValueError, match="cannot be empty"):
        preprocess_image(b"")
