from pathlib import Path

from omegaconf import OmegaConf


def test_training_config_contains_required_fields() -> None:
    """Verify that the training configuration contains required values."""

    config_path = Path("conf/config.yaml")
    cfg = OmegaConf.load(config_path)

    assert cfg.project.name == "sentinel"
    assert cfg.training.batch_size > 0
    assert cfg.training.learning_rate > 0
    assert cfg.training.epochs > 0
    assert cfg.model.num_classes == 10