from pathlib import Path

import pandas as pd
from sklearn.datasets import fetch_openml


def main() -> None:
    """Download MNIST from OpenML and save it as a CSV file."""

    project_root = Path(__file__).resolve().parents[1]
    output_directory = project_root / "data"
    output_file = output_directory / "mnist.csv"

    output_directory.mkdir(parents=True, exist_ok=True)

    print("Downloading MNIST from OpenML...")

    features, target = fetch_openml(
        name="mnist_784",
        version=1,
        as_frame=True,
        return_X_y=True,
    )

    dataset = pd.DataFrame(features)
    dataset["label"] = target.astype("int64")

    dataset.to_csv(output_file, index=False)

    print(f"MNIST dataset saved to: {output_file}")
    print(f"Number of rows: {len(dataset)}")
    print(f"Number of columns: {len(dataset.columns)}")


if __name__ == "__main__":
    main()