
from pathlib import Path

from hydra import compose, initialize_config_dir
from omegaconf import DictConfig


CONFIG_DIR = Path(__file__).resolve().parents[1] / "conf"


def load_training_config(
    overrides: list[str] | None = None,
) -> DictConfig:
    """Compose the training configuration using Hydra."""

    with initialize_config_dir(
        version_base=None,
        config_dir=str(CONFIG_DIR.resolve()),
    ):
        return compose(
            config_name="config",
            overrides=overrides or [],
        )


def test_training_config_contains_required_fields() -> None:
    """Verify generic training configuration requirements."""

    cfg = load_training_config()

    assert cfg.project.name
    assert cfg.training.batch_size > 0
    assert cfg.training.learning_rate > 0
    assert cfg.training.epochs > 0
    assert 0 < cfg.training.validation_ratio < 1
    assert cfg.training.random_seed >= 0

    assert cfg.model.name
    assert cfg.dataset.name
    assert cfg.dataset.project
    assert cfg.dataset.version
    assert cfg.dataset.file_name

    assert cfg.runtime.device


def test_training_config_supports_hydra_overrides() -> None:
    """Verify training parameters can be overridden without code changes."""

    cfg = load_training_config(
        overrides=[
            "training.batch_size=16",
            "training.epochs=2",
        ],
    )

    assert cfg.training.batch_size == 16
    assert cfg.training.epochs == 2
