import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from hydra import compose, initialize_config_dir
from omegaconf import DictConfig
from PIL import Image


IMAGE_WIDTH = 28
IMAGE_HEIGHT = 28
EXPECTED_PIXEL_COUNT = IMAGE_WIDTH * IMAGE_HEIGHT


def find_label_column(
    dataframe: pd.DataFrame,
) -> str:
    """Find the dataset label column."""

    for column in dataframe.columns:
        if str(column).lower() == "label":
            return str(column)

    raise ValueError(
        "MNIST dataset does not contain a label column."
    )


def resolve_validation_indices(
    total_samples: int,
    validation_ratio: float,
    random_seed: int,
) -> list[int]:
    """Recreate the same validation split used by training."""

    if not 0.0 < validation_ratio < 1.0:
        raise ValueError(
            "validation_ratio must be between 0 and 1."
        )

    validation_size = int(
        total_samples * validation_ratio
    )

    training_size = (
        total_samples - validation_size
    )

    generator = torch.Generator().manual_seed(
        random_seed
    )

    shuffled_indices = torch.randperm(
        total_samples,
        generator=generator,
    ).tolist()

    validation_indices = shuffled_indices[
        training_size:
    ]

    return [
        int(index)
        for index in validation_indices
    ]


def rotate_pixels(
    pixel_values: np.ndarray,
    angle: float,
) -> np.ndarray:
    """Rotate one MNIST image while preserving its dimensions."""

    if pixel_values.size != EXPECTED_PIXEL_COUNT:
        raise ValueError(
            "MNIST sample must contain "
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

    rotated_image = image.rotate(
        angle,
        resample=Image.Resampling.BILINEAR,
        expand=False,
        fillcolor=0,
    )

    return np.asarray(
        rotated_image,
        dtype=np.uint8,
    ).reshape(-1)


def select_balanced_samples(
    dataframe: pd.DataFrame,
    validation_indices: list[int],
    label_column: str,
    required_samples: int,
    random_seed: int,
) -> list[int]:
    """Select a deterministic class-balanced golden subset."""

    validation_frame = dataframe.iloc[
        validation_indices
    ]

    labels = sorted(
        validation_frame[
            label_column
        ].unique().tolist()
    )

    if not labels:
        raise ValueError(
            "Validation split contains no labels."
        )

    if required_samples % len(labels) != 0:
        raise ValueError(
            "required_samples must be divisible by "
            "the number of observed classes."
        )

    samples_per_class = (
        required_samples // len(labels)
    )

    rng = np.random.default_rng(
        random_seed
    )

    selected_indices: list[int] = []

    for label in labels:
        class_indices = (
            validation_frame[
                validation_frame[label_column] == label
            ]
            .index
            .to_numpy(
                dtype=np.int64
            )
        )

        if len(class_indices) < samples_per_class:
            raise ValueError(
                f"Class {label} does not contain enough "
                "validation samples."
            )

        shuffled_indices = rng.permutation(
            class_indices
        )

        selected_indices.extend(
            int(index)
            for index in shuffled_indices[
                :samples_per_class
            ]
        )

    return selected_indices


def build_golden_set(
    cfg: DictConfig,
) -> None:
    """Build the immutable MNIST golden evaluation dataset."""

    source_path = Path(
        str(
            cfg.gatekeeper.adapters.builder.source_path
        )
    )

    output_path = Path(
        str(
            cfg.gatekeeper.golden_set.path
        )
    )

    manifest_path = Path(
        str(
            cfg.gatekeeper.adapters.holdout.manifest_path
        )
    )

    required_samples = int(
        cfg.gatekeeper.golden_set.required_samples
    )

    random_seed = int(
        cfg.training.random_seed
    )

    validation_ratio = float(
        cfg.training.validation_ratio
    )

    rotation_angles = [
        float(angle)
        for angle in (
            cfg.gatekeeper.adapters.builder.rotation_angles
        )
    ]

    if not rotation_angles:
        raise ValueError(
            "At least one rotation angle is required."
        )

    if not source_path.is_file():
        raise FileNotFoundError(
            f"Source dataset was not found: {source_path}"
        )

    dataframe = pd.read_csv(
        source_path
    )

    if dataframe.empty:
        raise ValueError(
            "Source dataset cannot be empty."
        )

    label_column = find_label_column(
        dataframe
    )

    pixel_columns = [
        column
        for column in dataframe.columns
        if column != label_column
    ]

    if len(pixel_columns) != EXPECTED_PIXEL_COUNT:
        raise ValueError(
            "MNIST dataset must contain "
            f"{EXPECTED_PIXEL_COUNT} pixel columns."
        )

    validation_indices = resolve_validation_indices(
        total_samples=len(dataframe),
        validation_ratio=validation_ratio,
        random_seed=random_seed,
    )

    selected_indices = select_balanced_samples(
        dataframe=dataframe,
        validation_indices=validation_indices,
        label_column=label_column,
        required_samples=required_samples,
        random_seed=random_seed,
    )

    golden_rows: list[dict[str, Any]] = []
    manifest_samples: list[dict[str, Any]] = []

    for position, source_index in enumerate(
        selected_indices
    ):
        source_row = dataframe.loc[
            source_index
        ]

        pixel_values = source_row[
            pixel_columns
        ].to_numpy(
            dtype=np.uint8
        )

        angle = rotation_angles[
            position % len(rotation_angles)
        ]

        rotated_pixels = rotate_pixels(
            pixel_values,
            angle,
        )

        golden_row = {
            column: int(value)
            for column, value in zip(
                pixel_columns,
                rotated_pixels,
                strict=True,
            )
        }

        label = int(
            source_row[label_column]
        )

        golden_row[label_column] = label

        golden_rows.append(
            golden_row
        )

        manifest_samples.append(
            {
                "source_index": source_index,
                "label": label,
                "rotation_angle": angle,
            }
        )

    golden_dataframe = pd.DataFrame(
        golden_rows,
        columns=[
            *pixel_columns,
            label_column,
        ],
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    golden_dataframe.to_csv(
        output_path,
        index=False,
    )

    manifest = {
        "source_dataset": {
            "project": str(
                cfg.dataset.project
            ),
            "name": str(
                cfg.dataset.name
            ),
            "version": str(
                cfg.dataset.version
            ),
        },
        "random_seed": random_seed,
        "validation_ratio": validation_ratio,
        "required_samples": required_samples,
        "samples": manifest_samples,
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        f"Golden set created: {output_path}"
    )

    print(
        f"Golden samples: {len(golden_dataframe)}"
    )

    print(
        f"Manifest created: {manifest_path}"
    )

    print(
        "Class distribution:"
    )

    print(
        golden_dataframe[
            label_column
        ]
        .value_counts()
        .sort_index()
        .to_string()
    )


def main() -> None:
    """Load Hydra configuration and build the golden dataset."""

    config_directory = (
        Path.cwd() / "conf"
    )

    with initialize_config_dir(
        version_base=None,
        config_dir=str(
            config_directory.resolve()
        ),
    ):
        cfg = compose(
            config_name="config"
        )

    build_golden_set(
        cfg
    )


if __name__ == "__main__":
    main()