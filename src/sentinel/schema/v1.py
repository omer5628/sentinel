import base64
import binascii
from io import BytesIO
from typing import Literal, cast
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator


EXPECTED_IMAGE_WIDTH = 28
EXPECTED_IMAGE_HEIGHT = 28
EXPECTED_IMAGE_MODE = "L"


class ImageMessageV1(BaseModel):
    """Define the version 1 contract for incoming image messages."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )

    schema_version: Literal["v1"]
    event_id: UUID

    image_id: str = Field(
        min_length=1,
        max_length=200,
    )

    timestamp: float = Field(
        gt=0,
    )

    image_format: Literal["png"]

    image_base64: str = Field(
        min_length=1,
    )

    @field_validator("image_base64")
    @classmethod
    def validate_image_content(
        cls,
        encoded_image: str,
    ) -> str:
        """Validate the semantic quality of the encoded image."""

        try:
            raw_image = base64.b64decode(
                encoded_image,
                validate=True,
            )
        except (binascii.Error, ValueError) as error:
            raise ValueError(
                "image_base64 is not valid Base64."
            ) from error

        try:
            with Image.open(BytesIO(raw_image)) as image:
                image.verify()

            with Image.open(BytesIO(raw_image)) as image:
                if image.format != "PNG":
                    raise ValueError(
                        f"Expected PNG image, received {image.format!r}."
                    )

                expected_size = (
                    EXPECTED_IMAGE_WIDTH,
                    EXPECTED_IMAGE_HEIGHT,
                )

                if image.size != expected_size:
                    raise ValueError(
                        "Expected image dimensions "
                        f"{EXPECTED_IMAGE_WIDTH}x{EXPECTED_IMAGE_HEIGHT}, "
                        f"received {image.width}x{image.height}."
                    )

                if image.mode != EXPECTED_IMAGE_MODE:
                    raise ValueError(
                        "Expected grayscale image mode "
                        f"'{EXPECTED_IMAGE_MODE}', "
                        f"received '{image.mode}'."
                    )

                extrema = cast(
                    tuple[int, int],
                    image.getextrema(),
                )

                minimum_pixel, maximum_pixel = extrema

                if minimum_pixel < 0 or maximum_pixel > 255:
                    raise ValueError(
                        "Pixel values must be integers "
                        "in the range 0-255."
                    )

        except UnidentifiedImageError as error:
            raise ValueError(
                "image_base64 does not contain a supported image."
            ) from error

        return encoded_image