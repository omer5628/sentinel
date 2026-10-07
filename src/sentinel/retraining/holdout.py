import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import cast

import pandas as pd


HoldoutId = str | int

HoldoutFilter = Callable[
    [pd.DataFrame, frozenset[HoldoutId]],
    pd.DataFrame,
]


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


def load_holdout_filter(
    reference: str,
) -> HoldoutFilter:
    """Load a dataset-specific holdout filter plugin."""

    normalized_reference = reference.strip()

    if not normalized_reference:
        raise ValueError(
            "Holdout filter reference cannot be empty."
        )

    module_name, separator, attribute_name = (
        normalized_reference.partition(":")
    )

    if (
        not separator
        or not module_name.strip()
        or not attribute_name.strip()
    ):
        raise ValueError(
            "Holdout filter reference must use "
            "'module:attribute' format."
        )

    module = import_module(
        module_name.strip()
    )

    try:
        filter_function = getattr(
            module,
            attribute_name.strip(),
        )
    except AttributeError as error:
        raise ImportError(
            "Holdout filter was not found: "
            f"{normalized_reference}"
        ) from error

    if not callable(
        filter_function
    ):
        raise TypeError(
            "Configured holdout filter must be callable."
        )

    return cast(
        HoldoutFilter,
        filter_function,
    )


def apply_holdout_filter(
    dataframe: pd.DataFrame,
    manifest_path: Path,
    id_field: str,
    filter_reference: str,
) -> pd.DataFrame:
    """Apply the configured dataset-specific immutable holdout filter."""

    holdout_ids = load_holdout_ids(
        manifest_path=manifest_path,
        id_field=id_field,
    )

    filter_function = load_holdout_filter(
        filter_reference
    )

    filtered_dataframe = filter_function(
        dataframe,
        holdout_ids,
    )

    if filtered_dataframe.empty:
        raise ValueError(
            "Holdout filtering removed the entire base dataset."
        )

    return filtered_dataframe