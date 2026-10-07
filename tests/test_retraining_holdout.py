import json

import pytest

from sentinel.retraining.holdout import (
    load_holdout_ids,
)


def write_manifest(
    tmp_path,
    samples,
):
    """Write a temporary holdout manifest."""

    manifest_path = (
        tmp_path / "manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            {
                "samples": samples,
            }
        ),
        encoding="utf-8",
    )

    return manifest_path


def test_load_integer_holdout_ids(
    tmp_path,
) -> None:
    manifest_path = write_manifest(
        tmp_path,
        [
            {"source_index": 10},
            {"source_index": 20},
            {"source_index": 30},
        ],
    )

    result = load_holdout_ids(
        manifest_path,
        id_field="source_index",
    )

    assert result == frozenset(
        {
            10,
            20,
            30,
        }
    )


def test_load_string_holdout_ids(
    tmp_path,
) -> None:
    manifest_path = write_manifest(
        tmp_path,
        [
            {"image_id": "image-a"},
            {"image_id": "image-b"},
        ],
    )

    result = load_holdout_ids(
        manifest_path,
        id_field="image_id",
    )

    assert result == frozenset(
        {
            "image-a",
            "image-b",
        }
    )


def test_rejects_duplicate_holdout_ids(
    tmp_path,
) -> None:
    manifest_path = write_manifest(
        tmp_path,
        [
            {"source_index": 10},
            {"source_index": 10},
        ],
    )

    with pytest.raises(
        ValueError,
        match="duplicate",
    ):
        load_holdout_ids(
            manifest_path,
            id_field="source_index",
        )


def test_rejects_missing_id_field(
    tmp_path,
) -> None:
    manifest_path = write_manifest(
        tmp_path,
        [
            {"source_index": 10},
        ],
    )

    with pytest.raises(
        ValueError,
        match="does not contain",
    ):
        load_holdout_ids(
            manifest_path,
            id_field="image_id",
        )


def test_rejects_missing_manifest(
    tmp_path,
) -> None:
    with pytest.raises(
        FileNotFoundError,
    ):
        load_holdout_ids(
            tmp_path / "missing.json",
            id_field="source_index",
        )