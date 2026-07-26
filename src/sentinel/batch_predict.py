#Script for comparing the speed of 1,000 batch requests – Task 2.6
import argparse
import os
import time
from pathlib import Path
from uuid import uuid4

import psycopg2
import torch
from psycopg2.extras import execute_values
from torch import Tensor
from torch.nn import Module

from sentinel.features import preprocess_image


DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_POSTGRES_DATABASE = "sentinel"
DEFAULT_POSTGRES_USERNAME = "sentinel"
DEFAULT_POSTGRES_PASSWORD = "sentinel"

DEFAULT_MODEL_PATH = "artifacts/model.pt"
DEFAULT_BATCH_SIZE = 32
MODEL_VERSION = "v1"

SUPPORTED_IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp",
}

CLASS_NAMES = {class_index: str(class_index) for class_index in range(10)}


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(
        description="Run offline batch predictions for an image folder."
    )

    parser.add_argument(
        "input_directory",
        type=Path,
        help="Directory containing images to process.",
    )

    parser.add_argument(
        "--campaign-name",
        required=True,
        help="Name used to group the predictions in PostgreSQL.",
    )

    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path(DEFAULT_MODEL_PATH),
        help="Path to the TorchScript model.",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Number of images processed in one inference batch.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of images to process.",
    )

    return parser.parse_args()


def create_postgres_connection():
    """Create a PostgreSQL connection."""

    return psycopg2.connect(
        host=os.getenv(
            "POSTGRES_HOST",
            DEFAULT_POSTGRES_HOST,
        ),
        port=int(
            os.getenv(
                "POSTGRES_PORT",
                str(DEFAULT_POSTGRES_PORT),
            )
        ),
        dbname=os.getenv(
            "POSTGRES_DB",
            DEFAULT_POSTGRES_DATABASE,
        ),
        user=os.getenv(
            "POSTGRES_USER",
            DEFAULT_POSTGRES_USERNAME,
        ),
        password=os.getenv(
            "POSTGRES_PASSWORD",
            DEFAULT_POSTGRES_PASSWORD,
        ),
    )


def load_model(model_path: Path) -> Module:
    """Load the trained TorchScript model."""

    if not model_path.is_file():
        raise FileNotFoundError(f"Model file was not found: {model_path}")

    model = torch.jit.load(
        str(model_path),
        map_location="cpu",
    )
    model.eval()

    return model


def discover_images(
    input_directory: Path,
    limit: int | None,
) -> list[Path]:
    """Return supported images from a directory."""

    if not input_directory.is_dir():
        raise NotADirectoryError(f"Input directory was not found: {input_directory}")

    image_paths = sorted(
        path
        for path in input_directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )

    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero.")

        image_paths = image_paths[:limit]

    if not image_paths:
        raise ValueError(f"No supported images were found in: {input_directory}")

    return image_paths


def create_batches(
    image_paths: list[Path],
    batch_size: int,
) -> list[list[Path]]:
    """Split image paths into fixed-size batches."""

    if batch_size <= 0:
        raise ValueError("batch_size must be greater than zero.")

    return [
        image_paths[index : index + batch_size]
        for index in range(0, len(image_paths), batch_size)
    ]


def preprocess_batch(
    image_paths: list[Path],
) -> tuple[Tensor, list[Path]]:
    """Read and preprocess a batch of images."""

    tensors: list[Tensor] = []
    valid_paths: list[Path] = []

    for image_path in image_paths:
        try:
            raw_image = image_path.read_bytes()
            tensor = preprocess_image(raw_image)

            tensors.append(tensor.squeeze(0))
            valid_paths.append(image_path)

        except (OSError, ValueError) as error:
            print(
                f"Skipping invalid image '{image_path}': {error}",
                flush=True,
            )

    if not tensors:
        raise ValueError("The batch does not contain valid images.")

    return torch.stack(tensors), valid_paths


def predict_batch(
    model: Module,
    batch_tensor: Tensor,
) -> tuple[list[int], list[float]]:
    """Run inference for one batch."""

    with torch.inference_mode():
        logits = model(batch_tensor)
        probabilities = torch.softmax(logits, dim=1)

        confidence_values, predicted_classes = torch.max(
            probabilities,
            dim=1,
        )

    return (
        predicted_classes.cpu().tolist(),
        confidence_values.cpu().tolist(),
    )


def create_prediction_rows(
    image_paths: list[Path],
    predicted_classes: list[int],
    confidence_values: list[float],
    campaign_name: str,
) -> list[tuple[object, ...]]:
    """Create PostgreSQL rows from batch predictions."""

    rows: list[tuple[object, ...]] = []

    for image_path, predicted_class, confidence in zip(
        image_paths,
        predicted_classes,
        confidence_values,
        strict=True,
    ):
        predicted_label = CLASS_NAMES.get(predicted_class)

        if predicted_label is None:
            raise ValueError(f"Unsupported predicted class: {predicted_class}")

        rows.append(
            (
                str(uuid4()),
                image_path.stem,
                campaign_name,
                str(image_path),
                predicted_class,
                predicted_label,
                confidence,
                MODEL_VERSION,
            )
        )

    return rows


def write_predictions(
    postgres_connection,
    rows: list[tuple[object, ...]],
) -> None:
    """Write one prediction batch directly to PostgreSQL."""

    with postgres_connection.cursor() as cursor:
        execute_values(
            cursor,
            """
            INSERT INTO batch_predictions (
                prediction_id,
                image_id,
                campaign_name,
                image_path,
                predicted_class,
                predicted_label,
                confidence,
                model_version
            )
            VALUES %s
            """,
            rows,
        )

    postgres_connection.commit()


def run_batch_prediction(
    input_directory: Path,
    campaign_name: str,
    model_path: Path,
    batch_size: int,
    limit: int | None,
) -> None:
    """Process an image folder without using the serving API."""

    image_paths = discover_images(
        input_directory=input_directory,
        limit=limit,
    )

    model = load_model(model_path)
    batches = create_batches(
        image_paths=image_paths,
        batch_size=batch_size,
    )

    postgres_connection = create_postgres_connection()

    processed_count = 0
    failed_count = 0
    start_time = time.perf_counter()

    print(
        f"Starting batch prediction for {len(image_paths)} images.",
        flush=True,
    )
    print(
        f"Batch size: {batch_size} | Campaign: {campaign_name}",
        flush=True,
    )

    try:
        for batch_number, image_batch in enumerate(
            batches,
            start=1,
        ):
            try:
                batch_tensor, valid_paths = preprocess_batch(image_batch)

                predicted_classes, confidence_values = predict_batch(
                    model=model,
                    batch_tensor=batch_tensor,
                )

                rows = create_prediction_rows(
                    image_paths=valid_paths,
                    predicted_classes=predicted_classes,
                    confidence_values=confidence_values,
                    campaign_name=campaign_name,
                )

                write_predictions(
                    postgres_connection=postgres_connection,
                    rows=rows,
                )

                processed_count += len(rows)
                failed_count += len(image_batch) - len(valid_paths)

                print(
                    f"Batch {batch_number}/{len(batches)} completed. "
                    f"Processed: {processed_count}",
                    flush=True,
                )

            except Exception as error:
                postgres_connection.rollback()
                failed_count += len(image_batch)

                print(
                    f"Batch {batch_number} failed: {error}",
                    flush=True,
                )

    finally:
        postgres_connection.close()

    elapsed_seconds = time.perf_counter() - start_time

    throughput = processed_count / elapsed_seconds if elapsed_seconds > 0 else 0.0

    print("", flush=True)
    print("Batch prediction completed.", flush=True)
    print(f"Processed images: {processed_count}", flush=True)
    print(f"Failed images: {failed_count}", flush=True)
    print(f"Elapsed time: {elapsed_seconds:.2f} seconds", flush=True)
    print(
        f"Throughput: {throughput:.2f} images/second",
        flush=True,
    )


def main() -> None:
    """Run the batch prediction command."""

    arguments = parse_arguments()

    run_batch_prediction(
        input_directory=arguments.input_directory,
        campaign_name=arguments.campaign_name,
        model_path=arguments.model_path,
        batch_size=arguments.batch_size,
        limit=arguments.limit,
    )


if __name__ == "__main__":
    main()
