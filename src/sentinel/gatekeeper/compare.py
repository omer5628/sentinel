import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import DictConfig

from sentinel.gatekeeper.config import (
    load_gatekeeper_config,
)
from sentinel.gatekeeper.evaluator import (
    ComparisonResult,
    compare_models,
)
from sentinel.gatekeeper.metrics import (
    get_metric,
)
from sentinel.gatekeeper.plugins import (
    load_golden_set_adapter,
    load_model_adapter,
    load_model_artifact_resolver,
)
from sentinel.gatekeeper.policy import (
    GateDecision,
    evaluate_gate,
)


@dataclass(frozen=True)
class GatekeeperRunResult:
    """Represent one complete gatekeeper comparison run."""

    current_model_reference: str
    candidate_model_reference: str
    comparison: ComparisonResult
    decision: GateDecision


def _normalize_model_reference(
    model_reference: str,
    field_name: str,
) -> str:
    """Normalize and validate one immutable model reference."""

    normalized_reference = (
        model_reference.strip()
    )

    if not normalized_reference:
        raise ValueError(
            f"{field_name} cannot be empty."
        )

    return normalized_reference


def run_gatekeeper(
    cfg: DictConfig,
    current_model_reference: str,
    candidate_model_reference: str,
) -> GatekeeperRunResult:
    """Run the configured gatekeeper comparison."""

    gatekeeper_config = (
        load_gatekeeper_config(
            cfg
        )
    )

    if not gatekeeper_config.enabled:
        raise RuntimeError(
            "Gatekeeper is disabled."
        )

    current_reference = (
        _normalize_model_reference(
            current_model_reference,
            "Current model reference",
        )
    )

    candidate_reference = (
        _normalize_model_reference(
            candidate_model_reference,
            "Candidate model reference",
        )
    )

    if current_reference == candidate_reference:
        raise ValueError(
            "Current and candidate model references "
            "must be different."
        )

    golden_set_adapter = (
        load_golden_set_adapter(
            gatekeeper_config
            .golden_set_adapter_reference
        )
    )

    samples = golden_set_adapter.load(
        gatekeeper_config.golden_set_path
    )

    if (
        len(samples)
        != gatekeeper_config.required_samples
    ):
        raise ValueError(
            "Golden dataset sample count does not "
            "match the configured requirement: "
            f"expected "
            f"{gatekeeper_config.required_samples}, "
            f"got {len(samples)}."
        )

    artifact_resolver = (
        load_model_artifact_resolver(
            gatekeeper_config
            .model_artifact_resolver_reference
        )
    )

    current_local_reference = (
        artifact_resolver.resolve(
            current_reference
        )
    )

    candidate_local_reference = (
        artifact_resolver.resolve(
            candidate_reference
        )
    )

    model_adapter = load_model_adapter(
        gatekeeper_config
        .model_adapter_reference
    )

    metric = get_metric(
        gatekeeper_config.metric_name
    )

    comparison = compare_models(
        model_adapter=model_adapter,
        current_model_reference=(
            current_local_reference
        ),
        candidate_model_reference=(
            candidate_local_reference
        ),
        samples=samples,
        metric=metric,
    )

    decision = evaluate_gate(
        comparison=comparison,
        policy=gatekeeper_config.policy,
    )

    return GatekeeperRunResult(
        current_model_reference=(
            current_reference
        ),
        candidate_model_reference=(
            candidate_reference
        ),
        comparison=comparison,
        decision=decision,
    )


def _load_hydra_config() -> DictConfig:
    """Compose the project Hydra configuration."""

    config_dir = (
        Path(__file__)
        .resolve()
        .parents[3]
        / "conf"
    )

    if not config_dir.is_dir():
        raise FileNotFoundError(
            "Hydra configuration directory "
            "was not found: "
            f"{config_dir}"
        )

    with initialize_config_dir(
        version_base=None,
        config_dir=str(
            config_dir
        ),
    ):
        cfg = compose(
            config_name="config",
        )

    return cfg


def _build_argument_parser() -> argparse.ArgumentParser:
    """Build the gatekeeper command-line parser."""

    parser = argparse.ArgumentParser(
        description=(
            "Compare the current production model "
            "with a candidate model."
        )
    )

    parser.add_argument(
        "--current-model-reference",
        required=True,
        help=(
            "Immutable reference of the current "
            "production model."
        ),
    )

    parser.add_argument(
        "--candidate-model-reference",
        required=True,
        help=(
            "Immutable reference of the retrained "
            "candidate model."
        ),
    )

    return parser


def _print_result(
    result: GatekeeperRunResult,
) -> None:
    """Print machine-readable gatekeeper results."""

    action = (
        "PROMOTE"
        if result.decision.passed
        else "REJECT"
    )

    status = (
        "passed"
        if result.decision.passed
        else "failed"
    )

    print(
        f"gatekeeper_status={status}"
    )

    print(
        f"gatekeeper_action={action}"
    )

    print(
        "current_model_reference="
        f"{result.current_model_reference}"
    )

    print(
        "candidate_model_reference="
        f"{result.candidate_model_reference}"
    )

    print(
        "current_score="
        f"{result.comparison.current.score:.6f}"
    )

    print(
        "candidate_score="
        f"{result.comparison.candidate.score:.6f}"
    )

    print(
        "score_delta="
        f"{result.comparison.score_delta:.6f}"
    )

    print(
        "regression="
        f"{result.decision.regression:.6f}"
    )

    print(
        "gatekeeper_reason="
        f"{result.decision.reason}"
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    """Run the gatekeeper command-line interface."""

    parser = _build_argument_parser()

    args = parser.parse_args(
        argv
    )

    try:
        cfg = _load_hydra_config()

        result = run_gatekeeper(
            cfg=cfg.gatekeeper,
            current_model_reference=(
                args.current_model_reference
            ),
            candidate_model_reference=(
                args.candidate_model_reference
            ),
        )
    except Exception as error:
        print(
            "gatekeeper_status=error"
        )

        print(
            f"gatekeeper_error={error}"
        )

        return 2

    _print_result(
        result
    )

    return (
        0
        if result.decision.passed
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
