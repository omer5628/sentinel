from pathlib import Path

import numpy as np
import pandas as pd
from clearml import Dataset
from PIL import Image


DATASET_PROJECT = "Sentinel"
DATASET_NAME = "mnist"
DATASET_VERSION = "1.0.0"
DATASET_FILE_NAME = "mnist.csv"

OUTPUT_DIRECTORY = Path("data/campaign_v1")
IMAGE_COUNT = 1000
IMAGE_SIZE = 28


def main() -> None:
    """Export MNIST CSV rows as PNG files for batch prediction."""

    dataset = Dataset.get(
        dataset_project=DATASET_PROJECT,
        dataset_name=DATASET_NAME,
        dataset_version=DATASET_VERSION,
    )

    dataset_root = Path(dataset.get_local_copy())
    dataset_file = dataset_root / DATASET_FILE_NAME

    dataframe = pd.read_csv(dataset_file)

    label_column = next(
        column
        for column in dataframe.columns
        if column.lower() == "label"
    )

    pixel_columns = [
        column
        for column in dataframe.columns
        if column != label_column
    ]

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    for row_index in range(min(IMAGE_COUNT, len(dataframe))):
        pixel_values = dataframe.loc[
            dataframe.index[row_index],
            pixel_columns,
        ].to_numpy(dtype=np.uint8)

        image_array = pixel_values.reshape(IMAGE_SIZE, IMAGE_SIZE)
        image = Image.fromarray(image_array)

        label = int(dataframe.iloc[row_index][label_column])
        output_path = (
            OUTPUT_DIRECTORY
            / f"mnist_{row_index:05d}_label_{label}.png"
        )

        image.save(output_path)

    print(
        f"Exported {min(IMAGE_COUNT, len(dataframe))} images "
        f"to {OUTPUT_DIRECTORY.resolve()}"
    )


if __name__ == "__main__":
    main()