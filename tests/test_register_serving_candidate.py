"""Tests for safe registration of candidate models in ClearML Serving."""

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOOD_TASK_ID = "d" * 32
GOOD_MODEL_ID = "a" * 32
OTHER_MODEL_ID = "b" * 32


@pytest.fixture
def registration_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the CLI script without running its entry point."""

    monkeypatch.syspath_prepend(str(PROJECT_ROOT / "scripts"))
    return importlib.import_module("register_serving_candidate")


@pytest.fixture
def planned_command(registration_module: ModuleType) -> list[str]:
    """Prepare a model registration command without external calls."""

    cfg = registration_module.load_serving_config(
        PROJECT_ROOT / "conf/serving/mnist.yaml"
    )
    return registration_module.build_registration_command(
        cfg=cfg,
        task_id=GOOD_TASK_ID,
        model_id=GOOD_MODEL_ID,
        serving_version=35,
        preprocess_path=Path("/tmp/test-preprocess.py"),
    )


def test_registration_command_contains_model_and_contract(
    planned_command: list[str],
) -> None:
    """Register a unique endpoint version with the configured model contract."""

    command = planned_command
    assert command[:3] == ["clearml-serving", "--id", GOOD_TASK_ID]
    assert command[command.index("--model-id") + 1] == GOOD_MODEL_ID
    assert command[command.index("--version") + 1] == "35"
    assert command[command.index("--engine") + 1] == "triton"
    assert command[command.index("--input-size") + 1] == "[1,28,28]"
    assert command[command.index("--output-size") + 1] == "[10]"
    assert "canary" not in command
    assert "--weights" not in command


@pytest.mark.parametrize(
    ("task_id", "model_id", "serving_version"),
    [
        ("invalid", GOOD_MODEL_ID, 35),
        (GOOD_TASK_ID, "invalid", 35),
        (GOOD_TASK_ID, GOOD_MODEL_ID, 0),
        (GOOD_TASK_ID, GOOD_MODEL_ID, -1),
    ],
)
def test_registration_rejects_invalid_identifiers(
    registration_module: ModuleType,
    task_id: str,
    model_id: str,
    serving_version: int,
) -> None:
    """Reject malformed model IDs, task IDs, or Serving versions."""

    cfg = registration_module.load_serving_config(
        PROJECT_ROOT / "conf/serving/mnist.yaml"
    )
    with pytest.raises(ValueError):
        registration_module.build_registration_command(
            cfg=cfg,
            task_id=task_id,
            model_id=model_id,
            serving_version=serving_version,
            preprocess_path=Path("/tmp/test-preprocess.py"),
        )


def mock_endpoint_listing(
    monkeypatch: pytest.MonkeyPatch,
    registration_module: ModuleType,
    endpoints: dict[str, object],
) -> list[list[str]]:
    """Replace the remote endpoint listing with a deterministic fixture."""

    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        assert kwargs["check"] is True
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="ClearML Serving\nEndpoints:\n" + json.dumps(endpoints) + "\nCanary:\n{}\n",
            stderr="",
        )

    monkeypatch.setattr(registration_module.subprocess, "run", fake_run)
    return calls


def test_unused_version_is_safe(
    registration_module: ModuleType,
    planned_command: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow registration when the endpoint version is not occupied."""

    calls = mock_endpoint_listing(monkeypatch, registration_module, {})
    assert registration_module.assert_registration_is_safe(planned_command, GOOD_MODEL_ID)
    assert calls == [planned_command[:3] + ["model", "list"]]


def test_existing_version_for_same_model_is_idempotent(
    registration_module: ModuleType,
    planned_command: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Avoid re-registering an existing endpoint for the same model."""

    mock_endpoint_listing(
        monkeypatch,
        registration_module,
        {"sentinel-mnist/35": {"model_id": GOOD_MODEL_ID}},
    )
    assert not registration_module.assert_registration_is_safe(
        planned_command, GOOD_MODEL_ID
    )


def test_existing_version_for_other_model_is_blocked(
    registration_module: ModuleType,
    planned_command: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never overwrite another model assigned to the endpoint version."""

    mock_endpoint_listing(
        monkeypatch,
        registration_module,
        {"sentinel-mnist/35": {"model_id": OTHER_MODEL_ID}},
    )
    with pytest.raises(RuntimeError, match="Refusing to overwrite"):
        registration_module.assert_registration_is_safe(planned_command, GOOD_MODEL_ID)


def test_unverifiable_listing_is_blocked(
    registration_module: ModuleType,
    planned_command: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed if the Serving endpoint state cannot be confirmed."""

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="Unexpected output", stderr="")

    monkeypatch.setattr(registration_module.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="Cannot verify"):
        registration_module.assert_registration_is_safe(planned_command, GOOD_MODEL_ID)


def test_default_dry_run_never_calls_serving(
    registration_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Print the registration plan without invoking the ClearML CLI."""

    def forbidden_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("The CLI must not run during a dry run")

    monkeypatch.setattr(registration_module.subprocess, "run", forbidden_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "register_serving_candidate.py",
            "--config", str(PROJECT_ROOT / "conf/serving/mnist.yaml"),
            "--serving-task-id", GOOD_TASK_ID,
            "--candidate-model-id", GOOD_MODEL_ID,
            "--model-version", "retrain-35",
            "--serving-version", "35",
        ],
    )

    registration_module.main()

    output = capsys.readouterr().out
    assert "DRY RUN ONLY" in output
    assert "--version 35" in output
    assert "--weights" not in output
