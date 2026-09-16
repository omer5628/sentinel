from collections.abc import Mapping
from datetime import datetime

import torch
from torch.utils.data import TensorDataset

from sentinel.retraining.fetch_data import DatabaseConnection


def load_human_labeled_dataset(
    connection: DatabaseConnection,
    *,
    cutoff: datetime,
    discard_label: str,
    expected_sample_shape: tuple[int, ...],
    label_to_index: Mapping[str, int],
) -> TensorDataset:
    """Load human-labeled feature vectors eligible for retraining."""

    if not discard_label.strip():
        raise ValueError(
            "discard_label must not be empty."
        )

    if not expected_sample_shape:
        raise ValueError(
            "expected_sample_shape must not be empty."
        )

    if not label_to_index:
        raise ValueError(
            "label_to_index must not be empty."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT vector, label
            FROM feature_log
            WHERE label IS NOT NULL
              AND label <> %s
              AND labeled_at IS NOT NULL
              AND labeled_at <= %s
            ORDER BY labeled_at ASC, event_id ASC
            """,
            (
                discard_label,
                cutoff,
            ),
        )

        rows = cursor.fetchall()

    if not rows:
        empty_images = torch.empty(
            (0, *expected_sample_shape),
            dtype=torch.float32,
        )

        empty_labels = torch.empty(
            (0,),
            dtype=torch.long,
        )

        return TensorDataset(
            empty_images,
            empty_labels,
        )

    images: list[torch.Tensor] = []
    labels: list[int] = []

    stored_batched_shape = (
        1,
        *expected_sample_shape,
    )

    for vector_value, label_value in rows:
        if vector_value is None:
            raise ValueError(
                "Human-labeled row contains a null feature vector."
            )

        label_key = str(
            label_value
        ).strip()

        if label_key not in label_to_index:
            raise ValueError(
                "Human-labeled row contains an unknown label: "
                f"{label_key}"
            )

        image = torch.as_tensor(
            vector_value,
            dtype=torch.float32,
        )

        actual_shape = tuple(
            int(dimension)
            for dimension in image.shape
        )

        if actual_shape == stored_batched_shape:
            image = image.squeeze(0)

        elif actual_shape != expected_sample_shape:
            raise ValueError(
                "Human-labeled feature vector has an unexpected shape. "
                f"Expected {expected_sample_shape} "
                f"or {stored_batched_shape}, "
                f"received {actual_shape}."
            )

        images.append(
            image
        )

        labels.append(
            label_to_index[label_key]
        )

    image_tensor = torch.stack(
        images
    )

    label_tensor = torch.tensor(
        labels,
        dtype=torch.long,
    )

    return TensorDataset(
        image_tensor,
        label_tensor,
    )
