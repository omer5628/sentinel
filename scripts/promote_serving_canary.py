"""Promote a registered ClearML model into the existing Canary slot.

Only the model assigned to the non-production slot may change. The script
preserves the live routing weights and leaves the production model untouched.
Without --execute, it performs a read-only check and prints the planned call.
"""

import argparse
import json
import math
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf


HEX_ID = re.compile(r"[0-9a-fA-F]{32}")
SERVING_PREFIX = ["clearml-serving"]


@dataclass(frozen=True)
class ServingState:
    """Hold the endpoint and routing configuration reported by ClearML."""

    endpoints: dict[str, Any]
    canary: dict[str, Any]


@dataclass(frozen=True)
class PromotionPlan:
    """Describe a routing change without performing it."""

    command: list[str]
    original_endpoints: tuple[str, str]
    desired_endpoints: tuple[str, str]
    weights: tuple[float, float]
    production_index: int
    already_applied: bool


def _parse_section(output: str, heading: str) -> dict[str, Any]:
    """Decode an object from a named section of model-list output."""

    marker = f"{heading}:"
    if marker not in output:
        raise RuntimeError(f"Missing '{heading}' section in Serving state.")

    content = output.split(marker, 1)[1].lstrip()
    try:
        parsed, _ = json.JSONDecoder().raw_decode(content)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Invalid '{heading}' section in Serving state.") from error

    if not isinstance(parsed, dict):
        raise RuntimeError(f"'{heading}' must be a JSON object.")
    return parsed


def parse_serving_state(output: str) -> ServingState:
    """Parse the live model list without executing any endpoint changes."""

    return ServingState(
        endpoints=_parse_section(output, "Endpoints"),
        canary=_parse_section(output, "Canary"),
    )


def read_serving_state(task_id: str) -> ServingState:
    """Read the authoritative Serving Task endpoint assignments."""

    if HEX_ID.fullmatch(task_id) is None:
        raise ValueError("Serving Task ID must be a 32-character hexadecimal ID.")

    command = [*SERVING_PREFIX, "--id", task_id, "model", "list"]
    completed = subprocess.run(command, text=True, capture_output=True, check=True)
    return parse_serving_state(completed.stdout)


def _model_id_at(state: ServingState, endpoint: str) -> str:
    """Return the registered model ID or fail on missing endpoint metadata."""

    data = state.endpoints.get(endpoint)
    if not isinstance(data, dict) or not isinstance(data.get("model_id"), str):
        raise RuntimeError(f"Serving endpoint is not registered: {endpoint}")
    return data["model_id"].lower()


def plan_canary_promotion(
    state: ServingState,
    task_id: str,
    canary_endpoint: str,
    base_endpoint: str,
    production_model_id: str,
    candidate_model_id: str,
    candidate_serving_version: int,
) -> PromotionPlan:
    """Preserve live weights and the production slot while replacing Canary."""

    if HEX_ID.fullmatch(task_id) is None:
        raise ValueError("Invalid Serving Task ID.")
    if HEX_ID.fullmatch(production_model_id) is None:
        raise ValueError("Invalid production Model ID.")
    if HEX_ID.fullmatch(candidate_model_id) is None:
        raise ValueError("Invalid candidate Model ID.")
    if candidate_serving_version < 1:
        raise ValueError("Serving version must be positive.")
    if not base_endpoint or not canary_endpoint:
        raise ValueError("Both Serving endpoint names are required.")
    if production_model_id.lower() == candidate_model_id.lower():
        raise ValueError("Candidate must differ from the production model.")

    route = state.canary.get(canary_endpoint)
    if not isinstance(route, dict):
        raise RuntimeError("Canary endpoint is missing; refusing to create a new route.")
    if route.get("load_endpoint_prefix") is not None:
        raise RuntimeError("Prefix-based routing is not supported for this promotion.")

    raw_endpoints = route.get("load_endpoints")
    raw_weights = route.get("weights")
    if (
        not isinstance(raw_endpoints, list)
        or len(raw_endpoints) != 2
        or any(not isinstance(item, str) for item in raw_endpoints)
        or not isinstance(raw_weights, list)
        or len(raw_weights) != 2
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in raw_weights
        )
    ):
        raise RuntimeError("Canary must have exactly two valid endpoints and weights.")

    weights = (float(raw_weights[0]), float(raw_weights[1]))
    if not math.isclose(sum(weights), 1.0, rel_tol=0, abs_tol=1e-5):
        raise RuntimeError("Live Canary weights do not add up to 1.")

    previous = (raw_endpoints[0], raw_endpoints[1])
    production_matches = [
        index
        for index, endpoint in enumerate(previous)
        if _model_id_at(state, endpoint) == production_model_id.lower()
    ]
    if len(production_matches) != 1:
        raise RuntimeError("Expected exactly one production model in Canary routing.")

    production_index = production_matches[0]
    canary_index = 1 - production_index
    candidate_endpoint = f"{base_endpoint}/{candidate_serving_version}"
    if _model_id_at(state, candidate_endpoint) != candidate_model_id.lower():
        raise RuntimeError("Candidate must be registered to its Serving version first.")
    if candidate_endpoint == previous[production_index]:
        raise RuntimeError("Cannot replace the production endpoint.")

    desired = list(previous)
    desired[canary_index] = candidate_endpoint
    updated = (desired[0], desired[1])
    command = [
        *SERVING_PREFIX,
        "--id", task_id,
        "model", "canary",
        "--endpoint", canary_endpoint,
        "--weights", str(weights[0]), str(weights[1]),
        "--input-endpoints", *updated,
    ]
    return PromotionPlan(
        command=command,
        original_endpoints=previous,
        desired_endpoints=updated,
        weights=weights,
        production_index=production_index,
        already_applied=(previous == updated),
    )


def verify_canary_promotion(
    state: ServingState,
    canary_endpoint: str,
    plan: PromotionPlan,
    production_model_id: str,
    candidate_model_id: str,
) -> bool:
    """Check routing assignments and ensure original traffic weights remain."""

    route = state.canary.get(canary_endpoint)
    if not isinstance(route, dict):
        return False
    actual_endpoints = route.get("load_endpoints")
    actual_weights = route.get("weights")
    if actual_endpoints != list(plan.desired_endpoints) or not isinstance(actual_weights, list):
        return False
    if len(actual_weights) != 2:
        return False
    for actual, expected in zip(actual_weights, plan.weights):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return False
        if not math.isfinite(actual) or not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-8):
            return False

    try:
        return (
            _model_id_at(state, plan.desired_endpoints[plan.production_index])
            == production_model_id.lower()
            and _model_id_at(state, plan.desired_endpoints[1 - plan.production_index])
            == candidate_model_id.lower()
        )
    except RuntimeError:
        return False


def main() -> None:
    """Plan a Canary replacement or explicitly execute and verify it."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--serving-task-id", required=True)
    parser.add_argument("--production-model-id", required=True)
    parser.add_argument("--candidate-model-id", required=True)
    parser.add_argument("--serving-version", type=int, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    cfg = OmegaConf.load(args.config)
    task_id = args.serving_task_id
    canary_endpoint = str(cfg.endpoints.canary)
    base_endpoint = str(cfg.endpoints.base)

    state = read_serving_state(task_id)
    plan = plan_canary_promotion(
        state=state,
        task_id=task_id,
        canary_endpoint=canary_endpoint,
        base_endpoint=base_endpoint,
        production_model_id=args.production_model_id,
        candidate_model_id=args.candidate_model_id,
        candidate_serving_version=args.serving_version,
    )

    if plan.already_applied:
        print("Canary already points to the requested model; no change needed.")
        return

    print("Current endpoints:", *plan.original_endpoints)
    print("Desired endpoints:", *plan.desired_endpoints)
    print("Preserved weights:", *plan.weights)
    print("Planned command:", shlex.join(plan.command))
    if not args.execute:
        print("DRY RUN ONLY: Canary routing was not modified.")
        return

    # Refuse to proceed if a concurrent change occurred after planning.
    if read_serving_state(task_id) != state:
        raise RuntimeError("Serving state changed during planning; aborting.")

    subprocess.run(plan.command, check=True)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if verify_canary_promotion(
            read_serving_state(task_id),
            canary_endpoint,
            plan,
            args.production_model_id,
            args.candidate_model_id,
        ):
            print("Canary configuration verified; live inference not yet verified.")
            return
        time.sleep(3)
    raise RuntimeError("Canary configuration was not verified within 45 seconds.")


if __name__ == "__main__":
    main()
