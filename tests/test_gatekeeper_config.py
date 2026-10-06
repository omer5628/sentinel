import pytest
from omegaconf import OmegaConf

from sentinel.gatekeeper.config import (
    load_gatekeeper_config,
)


def create_config():
    """Create a valid generic gatekeeper configuration."""

    return OmegaConf.create(
        {
            "enabled": True,
            "golden_set": {
                "path": "data/golden_set.csv",
                "required_samples": 100,
            },
            "evaluation": {
                "metric": "accuracy",
                "direction": "maximize",
            },
            "policy": {
                "max_regression": 0.0,
                "candidate_score_threshold": None,
                "threshold_operator": "gte",
            },
        }
    )


def test_load_gatekeeper_config() -> None:
    cfg = create_config()

    result = load_gatekeeper_config(
        cfg
    )

    assert result.enabled is True
    assert str(result.golden_set_path) == (
        "data/golden_set.csv"
    )
    assert result.required_samples == 100
    assert result.metric_name == "accuracy"
    assert (
        result.policy.metric_direction
        == "maximize"
    )
    assert result.policy.max_regression == 0.0
    assert (
        result.policy.candidate_score_threshold
        is None
    )


def test_rejects_invalid_required_samples() -> None:
    cfg = create_config()

    cfg.golden_set.required_samples = 0

    with pytest.raises(
        ValueError,
        match="required_samples",
    ):
        load_gatekeeper_config(
            cfg
        )


def test_rejects_empty_metric() -> None:
    cfg = create_config()

    cfg.evaluation.metric = ""

    with pytest.raises(
        ValueError,
        match="metric cannot be empty",
    ):
        load_gatekeeper_config(
            cfg
        )


def test_rejects_invalid_metric_direction() -> None:
    cfg = create_config()

    cfg.evaluation.direction = "sideways"

    with pytest.raises(
        ValueError,
        match="Unsupported metric direction",
    ):
        load_gatekeeper_config(
            cfg
        )


def test_rejects_invalid_threshold_operator() -> None:
    cfg = create_config()

    cfg.policy.threshold_operator = "equal"

    with pytest.raises(
        ValueError,
        match="Unsupported threshold operator",
    ):
        load_gatekeeper_config(
            cfg
        )