
from io import BytesIO

import numpy as np
import torch
from PIL import Image
from torch import Tensor


MNIST_IMAGE_WIDTH = 28
MNIST_IMAGE_HEIGHT = 28


class MNISTImagePreprocessor:
    """Preprocess raw images for the existing MNIST CNN model."""

    def __call__(self, raw_bytes: bytes) -> Tensor:
        """Return a normalized tensor with shape [1, 1, 28, 28]."""

        if not raw_bytes:
            raise ValueError("Image bytes cannot be empty.")

        try:
            with Image.open(BytesIO(raw_bytes)) as image:
                grayscale_image = image.convert("L")

                resized_image = grayscale_image.resize(
                    (MNIST_IMAGE_WIDTH, MNIST_IMAGE_HEIGHT)
                )

                image_array = np.asarray(
                    resized_image,
                    dtype=np.float32,
                )

        except Exception as error:
            raise ValueError(
                "Could not decode the provided image bytes."
            ) from error

        normalized_array = image_array / 255.0

        tensor = torch.from_numpy(normalized_array)

        return tensor.unsqueeze(0).unsqueeze(0)
