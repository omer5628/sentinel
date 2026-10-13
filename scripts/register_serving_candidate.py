"""Prepare or register a candidate model in ClearML Serving.

This script does not change the Canary routing configuration. By default, it
prints the registration parameters without contacting ClearML Serving.
"""

import argparse
import json
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from omegaconf import DictConfig, OmegaConf

from render_serving_preprocess import render_preprocess


MODEL_ID_PATTERN = re.compile(r"[0-9a-fA-F]{32}")
MODEL_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def load_serving_config(path: Path) -> DictConfig:
    """Validate and return a model-specific serving contract."""

    cfg = OmegaConf.load(path)

    if cfg.provider != "clearml" or cfg.engine != "triton":
        raise ValueError("This registration adapter requires ClearML Triton.")

    if not str(cfg.endpoints.base).strip():
        raise ValueError("The base serving endpoint cannot be empty.")

    if not Path(str(cfg.preprocess.template)).is_file():
        raise ValueError("The configured preprocessing template does not exist.")

    return cfg


def build_registration_command(
    cfg: DictConfig,
    task_id: str,
    model_id: str,
    serving_version: int,
    preprocess_path: Path,
) -> list[str]:
    """Build a ClearML CLI command without executing it."""

    if MODEL_ID_PATTERN.fullmatch(task_id) is None:
        raise ValueError("Serving Task ID must be a 32-character hexadecimal ID.")

    if MODEL_ID_PATTERN.fullmatch(model_id) is None:
        raise ValueError("Candidate Model ID must be a 32-character hexadecimal ID.")

    if serving_version < 1:
        raise ValueError("Serving version must be a positive integer.")

    return [
        "clearml-serving",
        "--id",
        task_id,
        "model",
        "add",
        "--engine",
        str(cfg.engine),
        "--endpoint",
        str(cfg.endpoints.base),
        "--version",
        str(serving_version),
        "--model-id",
        model_id,
        "--preprocess",
        str(preprocess_path),
        "--input-size",
        "[" + ",".join(str(value) for value in cfg.input.size) + "]",
        "--input-type",
        str(cfg.input.type),
        "--input-name",
        str(cfg.input.name),
        "--output-size",
        "[" + ",".join(str(value) for value in cfg.output.size) + "]",
        "--output-type",
        str(cfg.output.type),
        "--output-name",
        str(cfg.output.name),
        "--aux-config",
        f"max_batch_size={int(cfg.triton.max_batch_size)}",
        (
            "dynamic_batching.max_queue_delay_microseconds="
            f"{int(cfg.triton.dynamic_batching.max_queue_delay_microseconds)}"
        ),
    ]



def assert_registration_is_safe(command: list[str], model_id: str) -> bool:
    """Refuse to overwrite an endpoint registered for another model."""

    list_command = command[:3] + ["model", "list"]
    result = subprocess.run(
        list_command,
        capture_output=True,
        text=True,
        check=True,
    )

    if "Endpoints:" not in result.stdout:
        raise RuntimeError("Cannot verify existing ClearML Serving endpoints.")

    endpoint_text = result.stdout.split("Endpoints:", 1)[1].lstrip()
    endpoints, _ = json.JSONDecoder().raw_decode(endpoint_text)
    if not isinstance(endpoints, dict):
        raise RuntimeError("Invalid ClearML Serving endpoint listing.")

    endpoint = command[command.index("--endpoint") + 1]
    version = command[command.index("--version") + 1]
    existing = endpoints.get(f"{endpoint}/{version}")

    if existing is None:
        return True

    if not isinstance(existing, dict) or existing.get("model_id") != model_id:
        raise RuntimeError(
            "Refusing to overwrite an existing Serving endpoint version."
        )

    print("Candidate is already registered to this endpoint version.")
    return False


def main() -> None:
    """Render candidate preprocessing and optionally register the model."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--serving-task-id", required=True)
    parser.add_argument("--candidate-model-id", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--serving-version", type=int, required=True)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Register the candidate model; omit for a local dry run.",
    )
    args = parser.parse_args()

    if MODEL_VERSION_PATTERN.fullmatch(args.model_version) is None:
        parser.error("Invalid model version.")

    cfg = load_serving_config(args.config)

    with tempfile.TemporaryDirectory(prefix="sentinel-serving-") as directory:
        preprocess_path = Path(directory) / "preprocess.py"
        render_preprocess(
            template_path=Path(str(cfg.preprocess.template)),
            output_path=preprocess_path,
            model_version=args.model_version,
        )

        command = build_registration_command(
            cfg=cfg,
            task_id=args.serving_task_id,
            model_id=args.candidate_model_id,
            serving_version=args.serving_version,
            preprocess_path=preprocess_path,
        )

        if not args.execute:
            print("DRY RUN ONLY: ClearML Serving was not modified.")
            print("Planned registration command:")
            print(shlex.join(command))
            print("The temporary preprocessing file will be cleaned up.")
            return

        if assert_registration_is_safe(command, args.candidate_model_id):
            subprocess.run(command, check=True)
            print("Candidate registered; Canary routing was not modified.")


if __name__ == "__main__":
    main()
