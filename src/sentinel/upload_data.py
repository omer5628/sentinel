from pathlib import Path

from clearml import Dataset


DATASET_PROJECT = "Sentinel"
DATASET_NAME = "mnist"
DATASET_VERSION = "1.0.0"


def main() -> None:
    """Upload and finalize the MNIST dataset in ClearML."""

    project_root = Path(__file__).resolve().parents[2]
    dataset_file = project_root / "data" / "mnist.csv"

    if not dataset_file.is_file():
        raise FileNotFoundError(
            f"Dataset file was not found: {dataset_file}"
        )

    dataset = Dataset.create(
        dataset_project=DATASET_PROJECT,
        dataset_name=DATASET_NAME,
        dataset_version=DATASET_VERSION,
        description="MNIST dataset for Project Sentinel.",
    )

    dataset.add_files(path=dataset_file)
    dataset.upload()
    dataset.finalize()

    print("Dataset uploaded successfully.")
    print(f"Dataset ID: {dataset.id}")
    print(f"Dataset project: {DATASET_PROJECT}")
    print(f"Dataset name: {DATASET_NAME}")
    print(f"Dataset version: {DATASET_VERSION}")


if __name__ == "__main__":
    main()