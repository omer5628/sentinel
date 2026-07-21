from io import BytesIO
from pathlib import Path

import hydra
import numpy as np
import pandas as pd
from clearml import Dataset, Task
from omegaconf import DictConfig, OmegaConf
from PIL import Image
from torch import Tensor

from sentinel.features import preprocess_image


def load_sample_tensor(dataset_file: Path) -> Tensor:
    """Load one MNIST CSV row and preprocess it as image bytes."""

    dataframe = pd.read_csv(dataset_file, nrows=1)

    if dataframe.empty:
        raise ValueError("The MNIST dataset is empty.")

    pixel_columns = [column for column in dataframe.columns if column != "label"]

    pixel_values = dataframe.loc[0, pixel_columns].to_numpy(dtype=np.uint8)

    if pixel_values.size != 28 * 28:
        raise ValueError(f"Expected 784 pixels, received {pixel_values.size}.")

    image_array = pixel_values.reshape(28, 28)
    image = Image.fromarray(image_array, mode="L")

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")

    return preprocess_image(image_buffer.getvalue())


@hydra.main(
    version_base=None,
    config_path="../../conf",
    config_name="config",
)
def main(cfg: DictConfig) -> None:
    """Run the Sentinel training entry point."""

    task = Task.init(
        project_name=cfg.project.name,
        task_name=cfg.project.experiment_name,
    )

    resolved_config = OmegaConf.to_container(
        cfg,
        resolve=True,
    )
    task.connect(resolved_config)

    dataset = Dataset.get(
        dataset_project=cfg.dataset.project,
        dataset_name=cfg.dataset.name,
        dataset_version=cfg.dataset.version,
        alias="training_dataset",
    )

    dataset_root = Path(dataset.get_local_copy())
    dataset_file = dataset_root / cfg.dataset.file_name

    if not dataset_file.is_file():
        raise FileNotFoundError(
            f"Dataset file was not found in ClearML: {dataset_file}"
        )

    sample_tensor = load_sample_tensor(dataset_file)

    print("Loaded training configuration:")
    print(OmegaConf.to_yaml(cfg))

    print(f"Project: {cfg.project.name}")
    print(f"Experiment: {cfg.project.experiment_name}")
    print(f"Dataset: {cfg.dataset.name}")
    print(f"Dataset version: {cfg.dataset.version}")
    print(f"Dataset ID: {dataset.id}")
    print(f"Dataset file: {dataset_file}")
    print(f"Model: {cfg.model.name}")
    print(f"Batch size: {cfg.training.batch_size}")
    print(f"Learning rate: {cfg.training.learning_rate}")
    print(f"Epochs: {cfg.training.epochs}")
    print(f"Device: {cfg.runtime.device}")
    print(f"Preprocessed sample shape: {tuple(sample_tensor.shape)}")
    print(f"Preprocessed sample dtype: {sample_tensor.dtype}")
    print(
        "Preprocessed sample range: "
        f"{sample_tensor.min().item():.4f}–"
        f"{sample_tensor.max().item():.4f}"
    )

    original_working_directory = Path(hydra.utils.get_original_cwd())
    config_directory = original_working_directory / "conf"

    print(f"Original working directory: {original_working_directory}")
    print(f"Configuration directory: {config_directory}")


if __name__ == "__main__":
    main()
