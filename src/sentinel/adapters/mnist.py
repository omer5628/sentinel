from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from sentinel.features import preprocess_image
from sentinel.gatekeeper.contracts import (
    GoldenSample,
)
from sentinel.retraining.holdout import HoldoutId


IMAGE_WIDTH = 28
IMAGE_HEIGHT = 28
EXPECTED_PIXEL_COUNT = (
    IMAGE_WIDTH * IMAGE_HEIGHT
)


def _row_to_image_bytes(
    pixel_values: np.ndarray,
) -> bytes:
    """Convert one MNIST pixel row into PNG bytes."""

    if pixel_values.size != EXPECTED_PIXEL_COUNT:
        raise ValueError(
            "MNIST golden sample must contain "
            f"{EXPECTED_PIXEL_COUNT} pixels."
        )

    image_array = np.asarray(
        pixel_values,
        dtype=np.uint8,
    ).reshape(
        IMAGE_HEIGHT,
        IMAGE_WIDTH,
    )

    image = Image.fromarray(
        image_array,
        mode="L",
    )

    buffer = BytesIO()

    image.save(
        buffer,
        format="PNG",
    )

    return buffer.getvalue()


def _find_label_column(
    dataframe: pd.DataFrame,
) -> str:
    """Find the label column without assuming letter casing."""

    for column in dataframe.columns:
        if str(column).lower() == "label":
            return str(column)

    raise ValueError(
        "MNIST golden set does not contain a label column."
    )


def _load_labels(
    dataframe: pd.DataFrame,
    label_column: str,
) -> np.ndarray:
    """Load and validate integer class labels."""

    raw_labels = (
        dataframe[label_column]
        .to_numpy()
    )

    try:
        label_values = np.asarray(
            raw_labels,
            dtype=np.float64,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "MNIST golden labels must be numeric."
        ) from error

    if not np.isfinite(
        label_values
    ).all():
        raise ValueError(
            "MNIST golden labels must be finite."
        )

    if not np.equal(
        label_values,
        np.floor(label_values),
    ).all():
        raise ValueError(
            "MNIST golden labels must be integers."
        )

    return np.asarray(
        label_values,
        dtype=np.int64,
    )


def _load_pixels(
    dataframe: pd.DataFrame,
    label_column: str,
) -> np.ndarray:
    """Load and validate raw MNIST pixel values."""

    pixel_dataframe = dataframe.drop(
        columns=[label_column]
    )

    if (
        pixel_dataframe.shape[1]
        != EXPECTED_PIXEL_COUNT
    ):
        raise ValueError(
            "MNIST golden set must contain "
            f"{EXPECTED_PIXEL_COUNT} pixel columns, "
            f"received {pixel_dataframe.shape[1]}."
        )

    raw_pixels = (
        pixel_dataframe.to_numpy()
    )

    try:
        pixel_matrix = np.asarray(
            raw_pixels,
            dtype=np.float32,
        )
    except (TypeError, ValueError) as error:
        raise ValueError(
            "MNIST golden pixels must be numeric."
        ) from error

    if not np.isfinite(
        pixel_matrix
    ).all():
        raise ValueError(
            "MNIST golden pixels must be finite."
        )

    if (
        (pixel_matrix < 0).any()
        or (pixel_matrix > 255).any()
    ):
        raise ValueError(
            "MNIST golden pixels must be between 0 and 255."
        )

    return pixel_matrix

def exclude_training_holdout_rows(
    dataframe: pd.DataFrame,
    holdout_ids: frozenset[HoldoutId],
) -> pd.DataFrame:
    """Exclude immutable golden-set source rows from MNIST training data."""

    if not holdout_ids:
        return dataframe.copy()

    source_indices: set[int] = set()

    for holdout_id in holdout_ids:
        if (
            isinstance(holdout_id, bool)
            or not isinstance(holdout_id, int)
        ):
            raise ValueError(
                "MNIST holdout identifiers must be integer source indices."
            )

        source_indices.add(
            holdout_id
        )

    available_indices = {
        int(index)
        for index in dataframe.index
    }

    missing_indices = (
        source_indices
        - available_indices
    )

    if missing_indices:
        missing_preview = sorted(
            missing_indices
        )[:10]

        raise ValueError(
            "MNIST holdout source indices were not found "
            "in the base dataset: "
            f"{missing_preview}"
        )

    filtered_dataframe = dataframe.drop(
        index=sorted(
            source_indices
        )
    )

    if len(filtered_dataframe) != (
        len(dataframe)
        - len(source_indices)
    ):
        raise RuntimeError(
            "Unexpected MNIST holdout filtering result."
        )

    return filtered_dataframe.copy()

class MNISTGoldenSetAdapter:
    """Load MNIST golden samples from a CSV file."""

    def load(
        self,
        dataset_path: Path,
    ) -> list[GoldenSample]:
        """Load and preprocess MNIST golden samples."""

        if not dataset_path.is_file():
            raise FileNotFoundError(
                "MNIST golden set was not found: "
                f"{dataset_path}"
            )

        dataframe = pd.read_csv(
            dataset_path
        )

        if dataframe.empty:
            raise ValueError(
                "MNIST golden set cannot be empty."
            )

        label_column = _find_label_column(
            dataframe
        )

        labels = _load_labels(
            dataframe,
            label_column,
        )

        pixel_matrix = _load_pixels(
            dataframe,
            label_column,
        )

        samples: list[GoldenSample] = []

        for pixel_values, label in zip(
            pixel_matrix,
            labels,
            strict=True,
        ):
            image_bytes = _row_to_image_bytes(
                pixel_values
            )

            features = preprocess_image(
                image_bytes
            )

            samples.append(
                GoldenSample(
                    features=features,
                    label=int(label),
                )
            )

        return samples