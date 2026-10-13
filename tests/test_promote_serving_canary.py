"""Tests for safe replacement of the registered Canary model."""

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/promote_serving_canary.py"
TASK_ID = "d" * 32
PRODUCTION_ID = "a" * 32
OLD_CANARY_ID = "b" * 32
CANDIDATE_ID = "c" * 32


@pytest.fixture
def module():
    """Load the CLI script without calling its entry point."""

    spec = importlib.util.spec_from_file_location("promote_serving_canary", SCRIPT)
    assert spec is not None and spec.loader is not None
    import sys

    instance = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = instance
    spec.loader.exec_module(instance)
    return instance


def serving_output(
    production_slot: int = 0,
    include_candidate: bool = True,
    weights: tuple[float, float] = (0.9, 0.1),
) -> str:
    """Generate representative ClearML Serving CLI output."""

    import json

    endpoints = {
        "sentinel-mnist/1": {"model_id": PRODUCTION_ID},
        "sentinel-mnist/2": {"model_id": OLD_CANARY_ID},
    }
    if include_candidate:
        endpoints["sentinel-mnist/35"] = {"model_id": CANDIDATE_ID}
    routed = ["sentinel-mnist/1", "sentinel-mnist/2"]
    if production_slot == 1:
        routed.reverse()
    canary = {
        "sentinel-mnist-canary": {
            "endpoint": "sentinel-mnist-canary",
            "weights": list(weights),
            "load_endpoints": routed,
            "load_endpoint_prefix": None,
        }
    }
    return (
        "clearml-serving CLI\nEndpoints:\n" + json.dumps(endpoints)
        + "\nModel Monitoring:\n{}\nCanary:\n" + json.dumps(canary)
    )


def plan(module, text: str, version: int = 35):
    """Build a promotion plan using deterministic CLI output."""

    return module.plan_canary_promotion(
        module.parse_serving_state(text),
        TASK_ID,
        "sentinel-mnist-canary",
        "sentinel-mnist",
        PRODUCTION_ID,
        CANDIDATE_ID,
        version,
    )


def test_preserves_90_10_and_production_endpoint(module) -> None:
    """Only the Canary route target is replaced."""

    planned = plan(module, serving_output())
    assert planned.original_endpoints == ("sentinel-mnist/1", "sentinel-mnist/2")
    assert planned.desired_endpoints == ("sentinel-mnist/1", "sentinel-mnist/35")
    assert planned.weights == (0.9, 0.1)
    assert planned.production_index == 0
    assert planned.command[:3] == ["clearml-serving", "--id", TASK_ID]
    assert planned.command[-2:] == ["sentinel-mnist/1", "sentinel-mnist/35"]
    assert planned.command[planned.command.index("--weights") + 1:][:2] == ["0.9", "0.1"]


def test_preserves_reversed_production_slot_and_custom_weights(module) -> None:
    """Never assume the production model always occupies the first slot."""

    planned = plan(module, serving_output(production_slot=1, weights=(0.25, 0.75)))
    assert planned.desired_endpoints == ("sentinel-mnist/35", "sentinel-mnist/1")
    assert planned.weights == (0.25, 0.75)
    assert planned.production_index == 1


def test_rejects_unregistered_candidate(module) -> None:
    """Do not route traffic to a model that is not registered."""

    with pytest.raises(RuntimeError, match="not registered"):
        plan(module, serving_output(include_candidate=False))


def test_rejects_missing_canary_configuration(module) -> None:
    """Never accidentally create a new live routing policy."""

    state = module.parse_serving_state(serving_output())
    state.canary.clear()
    with pytest.raises(RuntimeError, match="missing"):
        module.plan_canary_promotion(
            state, TASK_ID, "sentinel-mnist-canary", "sentinel-mnist",
            PRODUCTION_ID, CANDIDATE_ID, 35,
        )


def test_rejects_unknown_production_model(module) -> None:
    """Fail closed if the approved production model is no longer served."""

    state = module.parse_serving_state(serving_output())
    state.endpoints["sentinel-mnist/1"]["model_id"] = "e" * 32
    with pytest.raises(RuntimeError, match="production"):
        module.plan_canary_promotion(
            state, TASK_ID, "sentinel-mnist-canary", "sentinel-mnist",
            PRODUCTION_ID, CANDIDATE_ID, 35,
        )


def test_rejects_incorrect_weights(module) -> None:
    """Require consistent routing weights before any change."""

    with pytest.raises(RuntimeError, match="add up"):
        plan(module, serving_output(weights=(0.9, 0.2)))


def test_rejects_prefixed_routing(module) -> None:
    """Do not silently replace prefix-based selection rules."""

    state = module.parse_serving_state(serving_output())
    state.canary["sentinel-mnist-canary"]["load_endpoint_prefix"] = "sentinel-mnist"
    with pytest.raises(RuntimeError, match="Prefix"):
        module.plan_canary_promotion(
            state, TASK_ID, "sentinel-mnist-canary", "sentinel-mnist",
            PRODUCTION_ID, CANDIDATE_ID, 35,
        )


def test_verifies_actual_state_after_promotion(module) -> None:
    """Check both model IDs, target endpoints, and preserved weights."""

    original = module.parse_serving_state(serving_output())
    planned = module.plan_canary_promotion(
        original, TASK_ID, "sentinel-mnist-canary", "sentinel-mnist",
        PRODUCTION_ID, CANDIDATE_ID, 35,
    )
    assert not module.verify_canary_promotion(
        original, "sentinel-mnist-canary", planned, PRODUCTION_ID, CANDIDATE_ID
    )
    original.canary["sentinel-mnist-canary"]["load_endpoints"] = list(planned.desired_endpoints)
    assert module.verify_canary_promotion(
        original, "sentinel-mnist-canary", planned, PRODUCTION_ID, CANDIDATE_ID
    )
    original.canary["sentinel-mnist-canary"]["weights"] = [0.8, 0.2]
    assert not module.verify_canary_promotion(
        original, "sentinel-mnist-canary", planned, PRODUCTION_ID, CANDIDATE_ID
    )


def test_rejects_unparseable_response(module) -> None:
    """Fail rather than guessing remote Serving state."""

    with pytest.raises(RuntimeError, match="Canary"):
        module.parse_serving_state("Endpoints:\n{}\n")


def test_detects_idempotent_repeated_promotion(module) -> None:
    """Repeating an already applied promotion does not require an update."""

    state = module.parse_serving_state(serving_output())
    state.canary["sentinel-mnist-canary"]["load_endpoints"][1] = "sentinel-mnist/35"
    result = module.plan_canary_promotion(
        state, TASK_ID, "sentinel-mnist-canary", "sentinel-mnist",
        PRODUCTION_ID, CANDIDATE_ID, 35,
    )
    assert result.already_applied
