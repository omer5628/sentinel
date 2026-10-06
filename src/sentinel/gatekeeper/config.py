from dataclasses import dataclass
from pathlib import Path
from typing import cast

from omegaconf import DictConfig

from sentinel.gatekeeper.policy import (
    GatePolicy,
    MetricDirection,
    ThresholdOperator,
)


SUPPORTED_METRIC_DIRECTIONS = {
    "maximize",
    "minimize",
}

SUPPORTED_THRESHOLD_OPERATORS = {
    "gte",
    "lte",
}


@dataclass(frozen=True)
class GatekeeperConfig:
    """Represent resolved generic gatekeeper configuration."""

    enabled: bool
    golden_set_path: Path
    required_samples: int
    metric_name: str
    policy: GatePolicy


def load_gatekeeper_config(
    cfg: DictConfig,
) -> GatekeeperConfig:
    """Load and validate gatekeeper configuration from Hydra."""

    enabled = bool(
        cfg.enabled
    )

    golden_set_path = Path(
        str(cfg.golden_set.path)
    )

    if not str(golden_set_path).strip():
        raise ValueError(
            "Golden set path cannot be empty."
        )

    required_samples = int(
        cfg.golden_set.required_samples
    )

    if required_samples <= 0:
        raise ValueError(
            "Golden set required_samples must be greater than zero."
        )

    metric_name = str(
        cfg.evaluation.metric
    ).strip()

    if not metric_name:
        raise ValueError(
            "Evaluation metric cannot be empty."
        )

    raw_direction = str(
        cfg.evaluation.direction
    ).strip()

    if raw_direction not in SUPPORTED_METRIC_DIRECTIONS:
        raise ValueError(
            "Unsupported metric direction: "
            f"{raw_direction}"
        )

    metric_direction = cast(
        MetricDirection,
        raw_direction,
    )

    max_regression = float(
        cfg.policy.max_regression
    )

    raw_operator = str(
        cfg.policy.threshold_operator
    ).strip()

    if raw_operator not in SUPPORTED_THRESHOLD_OPERATORS:
        raise ValueError(
            "Unsupported threshold operator: "
            f"{raw_operator}"
        )

    threshold_operator = cast(
        ThresholdOperator,
        raw_operator,
    )

    raw_threshold = (
        cfg.policy.candidate_score_threshold
    )

    candidate_score_threshold = (
        None
        if raw_threshold is None
        else float(raw_threshold)
    )

    policy = GatePolicy(
        metric_direction=metric_direction,
        max_regression=max_regression,
        candidate_score_threshold=(
            candidate_score_threshold
        ),
        threshold_operator=threshold_operator,
    )

    return GatekeeperConfig(
        enabled=enabled,
        golden_set_path=golden_set_path,
        required_samples=required_samples,
        metric_name=metric_name,
        policy=policy,
    )