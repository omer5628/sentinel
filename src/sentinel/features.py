from io import BytesIO

import numpy as np
import torch
from PIL import Image
from torch import Tensor


IMAGE_WIDTH = 28
IMAGE_HEIGHT = 28


def preprocess_image(raw_bytes: bytes) -> Tensor:
    """Convert raw image bytes into a normalized MNIST tensor."""

    if not raw_bytes:
        raise ValueError("Image bytes cannot be empty.")

    try:
        with Image.open(BytesIO(raw_bytes)) as image:
            grayscale_image = image.convert("L")
            resized_image = grayscale_image.resize((IMAGE_WIDTH, IMAGE_HEIGHT))
            image_array = np.asarray(
                resized_image,
                dtype=np.float32,
            )
    except Exception as error:
        raise ValueError("Could not decode the provided image bytes.") from error

    normalized_array = image_array / 255.0

    tensor = torch.from_numpy(normalized_array)
    tensor = tensor.unsqueeze(0).unsqueeze(0)

    return tensor
