from pathlib import Path

import pytest

from sentinel.adapters import clearml_model
from sentinel.adapters.clearml_model import (
    ClearMLModelArtifactResolver,
)


def test_resolves_clearml_model_to_local_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_path = (
        tmp_path / "model.pt"
    )

    model_path.write_bytes(
        b"fake-model"
    )

    captured_model_ids: list[str] = []

    class FakeInputModel:
        def __init__(
            self,
            model_id: str,
        ) -> None:
            captured_model_ids.append(
                model_id
            )

        def get_local_copy(
            self,
            *,
            raise_on_error: bool = False,
        ) -> str:
            assert raise_on_error is True

            return str(
                model_path
            )

    monkeypatch.setattr(
        clearml_model,
        "InputModel",
        FakeInputModel,
    )

    resolver = (
        ClearMLModelArtifactResolver()
    )

    resolved_path = resolver.resolve(
        "957c15c4b33848b4841141074c66bdb8"
    )

    assert resolved_path == str(
        model_path
    )

    assert captured_model_ids == [
        "957c15c4b33848b4841141074c66bdb8"
    ]


def test_rejects_empty_clearml_model_reference() -> None:
    resolver = (
        ClearMLModelArtifactResolver()
    )

    with pytest.raises(
        ValueError,
        match=(
            "ClearML model reference "
            "cannot be empty"
        ),
    ):
        resolver.resolve(
            "   "
        )


def test_rejects_missing_clearml_local_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeInputModel:
        def __init__(
            self,
            model_id: str,
        ) -> None:
            self.model_id = model_id

        def get_local_copy(
            self,
            *,
            raise_on_error: bool = False,
        ) -> str:
            return ""

    monkeypatch.setattr(
        clearml_model,
        "InputModel",
        FakeInputModel,
    )

    resolver = (
        ClearMLModelArtifactResolver()
    )

    with pytest.raises(
        FileNotFoundError,
        match=(
            "ClearML model artifact "
            "could not be resolved"
        ),
    ):
        resolver.resolve(
            "candidate-model-id"
        )


def test_rejects_nonexistent_resolved_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_path = (
        tmp_path / "missing-model.pt"
    )

    class FakeInputModel:
        def __init__(
            self,
            model_id: str,
        ) -> None:
            self.model_id = model_id

        def get_local_copy(
            self,
            *,
            raise_on_error: bool = False,
        ) -> str:
            return str(
                missing_path
            )

    monkeypatch.setattr(
        clearml_model,
        "InputModel",
        FakeInputModel,
    )

    resolver = (
        ClearMLModelArtifactResolver()
    )

    with pytest.raises(
        FileNotFoundError,
        match=(
            "Resolved ClearML model artifact "
            "does not exist"
        ),
    ):
        resolver.resolve(
            "candidate-model-id"
        )