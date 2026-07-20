from pathlib import Path

import hydra
from omegaconf import DictConfig, OmegaConf


@hydra.main(
    version_base=None,
    config_path="../../conf",
    config_name="config",
)
def main(cfg: DictConfig) -> None:
    """Run the Sentinel training entry point."""

    print("Loaded training configuration:")
    print(OmegaConf.to_yaml(cfg))

    print(f"Project: {cfg.project.name}")
    print(f"Experiment: {cfg.project.experiment_name}")
    print(f"Dataset: {cfg.dataset.name}")
    print(f"Model: {cfg.model.name}")
    print(f"Batch size: {cfg.training.batch_size}")
    print(f"Learning rate: {cfg.training.learning_rate}")
    print(f"Epochs: {cfg.training.epochs}")
    print(f"Device: {cfg.runtime.device}")

    original_working_directory = hydra.utils.get_original_cwd()
    config_directory = Path(original_working_directory) / "conf"

    print(f"Original working directory: {original_working_directory}")
    print(f"Configuration directory: {config_directory}")


if __name__ == "__main__":
    main()
