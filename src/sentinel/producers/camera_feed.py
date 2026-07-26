import base64
import json
import os
import random
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd
import pika
from clearml import Dataset
from PIL import Image


QUEUE_NAME = "video_stream"
FRAMES_PER_SECOND = 5
FRAME_INTERVAL_SECONDS = 1 / FRAMES_PER_SECOND

DEFAULT_RABBITMQ_HOST = "localhost"
DEFAULT_RABBITMQ_PORT = 5672
DEFAULT_RABBITMQ_USERNAME = "sentinel"
DEFAULT_RABBITMQ_PASSWORD = "sentinel"

DATASET_PROJECT = "Sentinel"
DATASET_NAME = "mnist"
DATASET_VERSION = "1.0.0"
DATASET_FILE_NAME = "mnist.csv"

IMAGE_WIDTH = 28
IMAGE_HEIGHT = 28
PIXEL_COUNT = IMAGE_WIDTH * IMAGE_HEIGHT


def load_dataset() -> pd.DataFrame:
    """Fetch the versioned MNIST dataset from ClearML."""

    dataset = Dataset.get(
        dataset_project=DATASET_PROJECT,
        dataset_name=DATASET_NAME,
        dataset_version=DATASET_VERSION,
    )

    dataset_root = Path(dataset.get_local_copy())
    dataset_file = dataset_root / DATASET_FILE_NAME

    if not dataset_file.is_file():
        raise FileNotFoundError(f"MNIST dataset file was not found: {dataset_file}")

    dataframe = pd.read_csv(dataset_file)

    if dataframe.empty:
        raise ValueError("The MNIST dataset is empty.")

    return dataframe


def extract_pixel_columns(dataframe: pd.DataFrame) -> list[str]:
    """Return the columns containing MNIST pixel values."""

    pixel_columns = [
        column for column in dataframe.columns if column.lower() != "label"
    ]

    if len(pixel_columns) != PIXEL_COUNT:
        raise ValueError(
            f"Expected {PIXEL_COUNT} pixel columns, received {len(pixel_columns)}."
        )

    return pixel_columns


def row_to_png_bytes(
    dataframe: pd.DataFrame,
    pixel_columns: list[str],
    row_index: int,
) -> bytes:
    """Convert one MNIST CSV row into grayscale PNG bytes."""

    pixel_values = dataframe.iloc[row_index][pixel_columns].to_numpy(dtype="uint8")

    image_array = pixel_values.reshape(
        IMAGE_HEIGHT,
        IMAGE_WIDTH,
    )
    image = Image.fromarray(image_array)

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")

    return image_buffer.getvalue()


def create_message(image_bytes: bytes, row_index: int) -> bytes:
    """Create a serialized RabbitMQ message."""

    event_id = str(uuid4())
    image_id = f"mnist-{row_index}-{event_id}"

    message: dict[str, Any] = {
        "event_id": event_id,
        "image_id": image_id,
        "timestamp": time.time(),
        "image_format": "png",
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
    }

    return json.dumps(message).encode("utf-8")


def create_rabbitmq_connection() -> pika.BlockingConnection:
    """Create a blocking connection to RabbitMQ."""

    host = os.getenv("RABBITMQ_HOST", DEFAULT_RABBITMQ_HOST)
    port = int(os.getenv("RABBITMQ_PORT", str(DEFAULT_RABBITMQ_PORT)))
    username = os.getenv(
        "RABBITMQ_USERNAME",
        DEFAULT_RABBITMQ_USERNAME,
    )
    password = os.getenv(
        "RABBITMQ_PASSWORD",
        DEFAULT_RABBITMQ_PASSWORD,
    )

    credentials = pika.PlainCredentials(
        username=username,
        password=password,
    )

    parameters = pika.ConnectionParameters(
        host=host,
        port=port,
        credentials=credentials,
        heartbeat=60,
        blocked_connection_timeout=30,
    )

    return pika.BlockingConnection(parameters)


def run_producer() -> None:
    """Continuously publish random MNIST images to RabbitMQ."""

    print("Loading the MNIST dataset from ClearML...", flush=True)
    dataframe = load_dataset()
    print(f"Dataset loaded successfully: {len(dataframe)} rows.", flush=True)

    print("Validating pixel columns...", flush=True)
    pixel_columns = extract_pixel_columns(dataframe)
    print("Pixel columns validated successfully.", flush=True)

    print("Connecting to RabbitMQ...", flush=True)
    connection = create_rabbitmq_connection()
    print("Connected to RabbitMQ successfully.", flush=True)

    channel = connection.channel()

    print(f"Declaring queue '{QUEUE_NAME}'...", flush=True)
    channel.queue_declare(
        queue=QUEUE_NAME,
        durable=True,
    )

    print(
        f"Producer started. Publishing up to "
        f"{FRAMES_PER_SECOND} frames per second "
        f"to queue '{QUEUE_NAME}'.",
        flush=True,
    )

    try:
        while True:
            row_index = random.randrange(len(dataframe))

            image_bytes = row_to_png_bytes(
                dataframe=dataframe,
                pixel_columns=pixel_columns,
                row_index=row_index,
            )

            message_body = create_message(
                image_bytes=image_bytes,
                row_index=row_index,
            )

            channel.basic_publish(
                exchange="",
                routing_key=QUEUE_NAME,
                body=message_body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                ),
            )

            print(
                f"Published MNIST row {row_index} to queue '{QUEUE_NAME}'.",
                flush=True,
            )

            time.sleep(FRAME_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("Producer stopped by user.", flush=True)
    finally:
        if connection.is_open:
            connection.close()


def main() -> None:
    """Run the MNIST camera feed simulator."""

    run_producer()


if __name__ == "__main__":
    main()
