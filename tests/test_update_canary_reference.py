"""Tests for the generic Git Canary-reference update helper."""

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def reference_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Import the standalone CLI the same way Jenkins executes it."""

    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(project_root / "scripts"))
    sys.modules.pop("update_canary_reference", None)
    return importlib.import_module("update_canary_reference")


OLD = "a" * 32
NEW = "b" * 32
BASE = (
    "# Production environment\n"
    "model:\n"
    f'  productionReference: "{OLD}"\n'
    f'  canaryReference: "{OLD}" # comment\n'
    "api:\n  replicaCount: 3\n"
)


def test_changes_only_canary_reference(reference_module: ModuleType) -> None:
    result = reference_module.update_canary_reference(BASE, OLD, NEW)
    assert f'  canaryReference: "{NEW}" # comment' in result
    assert f'  productionReference: "{OLD}"' in result
    assert "api:\n  replicaCount: 3\n" in result


def test_idempotent(reference_module: ModuleType) -> None:
    result = reference_module.update_canary_reference(BASE, OLD, OLD)
    assert result == BASE


def test_rejects_stale_old_reference(reference_module: ModuleType) -> None:
    with pytest.raises(ValueError, match="changed"):
        reference_module.update_canary_reference(BASE, NEW, OLD)


def test_rejects_missing_canary_reference(reference_module: ModuleType) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        reference_module.update_canary_reference(BASE.replace("canaryReference:", "otherReference:"), OLD, NEW)


def test_rejects_bad_identifier(reference_module: ModuleType) -> None:
    with pytest.raises(ValueError, match="32-character"):
        reference_module.update_canary_reference(BASE, OLD, "not-a-model")


def test_rejects_duplicate_reference(reference_module: ModuleType) -> None:
    duplicate = BASE.replace(
        "api:\n", f'  canaryReference: "{OLD}"\napi:\n'
    )
    with pytest.raises(ValueError, match="exactly one"):
        reference_module.update_canary_reference(duplicate, OLD, NEW)


def test_preserves_single_quoted_value_and_crlf(reference_module: ModuleType) -> None:
    source = f"model:\r\n  canaryReference: '{OLD}'\r\nother: true\r\n"
    result = reference_module.update_canary_reference(source, OLD, NEW)
    assert result == f"model:\r\n  canaryReference: '{NEW}'\r\nother: true\r\n"


def test_read_canary_reference(reference_module: ModuleType) -> None:
    assert reference_module.read_canary_reference(BASE) == OLD
