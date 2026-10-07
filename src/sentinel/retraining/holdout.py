import json
from pathlib import Path


HoldoutId = str | int


def load_holdout_ids(
    manifest_path: Path,
    id_field: str,
) -> frozenset[HoldoutId]:
    """Load immutable sample identifiers from a holdout manifest."""

    if not manifest_path.is_file():
        raise FileNotFoundError(
            "Holdout manifest was not found: "
            f"{manifest_path}"
        )

    normalized_id_field = id_field.strip()

    if not normalized_id_field:
        raise ValueError(
            "Holdout ID field cannot be empty."
        )

    try:
        payload = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as error:
        raise ValueError(
            "Holdout manifest contains invalid JSON."
        ) from error

    if not isinstance(payload, dict):
        raise ValueError(
            "Holdout manifest root must be an object."
        )

    samples = payload.get(
        "samples"
    )

    if not isinstance(samples, list):
        raise ValueError(
            "Holdout manifest must contain a samples list."
        )

    if not samples:
        raise ValueError(
            "Holdout manifest samples cannot be empty."
        )

    holdout_ids: list[HoldoutId] = []

    for position, sample in enumerate(
        samples
    ):
        if not isinstance(sample, dict):
            raise ValueError(
                "Holdout manifest sample "
                f"{position} must be an object."
            )

        if normalized_id_field not in sample:
            raise ValueError(
                "Holdout manifest sample "
                f"{position} does not contain "
                f"'{normalized_id_field}'."
            )

        sample_id = sample[
            normalized_id_field
        ]

        if isinstance(sample_id, bool) or not isinstance(
            sample_id,
            (str, int),
        ):
            raise ValueError(
                "Holdout sample identifiers must be "
                "strings or integers."
            )

        if (
            isinstance(sample_id, str)
            and not sample_id.strip()
        ):
            raise ValueError(
                "Holdout sample identifiers cannot be empty."
            )

        holdout_ids.append(
            sample_id
        )

    unique_ids = frozenset(
        holdout_ids
    )

    if len(unique_ids) != len(holdout_ids):
        raise ValueError(
            "Holdout manifest contains duplicate sample identifiers."
        )

    return unique_ids