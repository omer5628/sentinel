from io import BytesIO
from pathlib import Path

import hydra
import numpy as np
import pandas as pd
import torch
from clearml import Dataset, Task
from omegaconf import DictConfig, OmegaConf
from PIL import Image
from torch import Tensor
from torch.nn import CrossEntropyLoss, Module
from torch.optim import Adam
from torch.utils.data import DataLoader, TensorDataset, random_split

from sentinel.features import preprocess_image
from sentinel.model import MNISTClassifier


IMAGE_WIDTH = 28
IMAGE_HEIGHT = 28
MODEL_OUTPUT_PATH = Path("artifacts/model.pt")


def row_to_image_bytes(pixel_values: np.ndarray) -> bytes:
    """Convert one MNIST pixel row into grayscale PNG bytes."""

    if pixel_values.size != IMAGE_WIDTH * IMAGE_HEIGHT:
        raise ValueError(f"Expected 784 pixels, received {pixel_values.size}.")

    image_array = pixel_values.astype(np.uint8).reshape(
        IMAGE_HEIGHT,
        IMAGE_WIDTH,
    )
    image = Image.fromarray(image_array)

    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")

    return image_buffer.getvalue()


def load_tensor_dataset(dataset_file: Path) -> TensorDataset:
    """Load MNIST CSV data using the shared preprocessing function."""

    dataframe = pd.read_csv(dataset_file)

    if dataframe.empty:
        raise ValueError("The MNIST dataset is empty.")

    label_column = next(
        (column for column in dataframe.columns if column.lower() == "label"),
        None,
    )

    if label_column is None:
        raise ValueError("The MNIST dataset does not contain a label column.")

    labels = torch.tensor(
        dataframe[label_column].to_numpy(dtype=np.int64),
        dtype=torch.long,
    )

    pixel_dataframe = dataframe.drop(columns=[label_column])
    pixel_matrix = pixel_dataframe.to_numpy(dtype=np.uint8)

    if pixel_matrix.shape[1] != IMAGE_WIDTH * IMAGE_HEIGHT:
        raise ValueError(
            f"Expected 784 pixel columns, received {pixel_matrix.shape[1]}."
        )

    processed_images: list[Tensor] = []

    for pixel_values in pixel_matrix:
        image_bytes = row_to_image_bytes(pixel_values)
        image_tensor = preprocess_image(image_bytes)
        processed_images.append(image_tensor.squeeze(0))

    images = torch.stack(processed_images)

    return TensorDataset(images, labels)


def create_data_loaders(
    dataset: TensorDataset,
    batch_size: int,
    validation_ratio: float,
    random_seed: int,
) -> tuple[DataLoader, DataLoader]:
    """Split the dataset and create training and validation loaders."""

    if not 0.0 < validation_ratio < 1.0:
        raise ValueError("validation_ratio must be between 0 and 1.")

    validation_size = int(len(dataset) * validation_ratio)
    training_size = len(dataset) - validation_size

    generator = torch.Generator().manual_seed(random_seed)

    training_dataset, validation_dataset = random_split(
        dataset,
        lengths=[training_size, validation_size],
        generator=generator,
    )

    training_loader = DataLoader(
        training_dataset,
        batch_size=batch_size,
        shuffle=True,
    )

    validation_loader = DataLoader(
        validation_dataset,
        batch_size=batch_size,
        shuffle=False,
    )

    return training_loader, validation_loader


def train_one_epoch(
    model: Module,
    data_loader: DataLoader,
    loss_function: CrossEntropyLoss,
    optimizer: Adam,
    device: torch.device,
) -> tuple[float, float]:
    """Train the model for one epoch."""

    model.train()

    total_loss = 0.0
    correct_predictions = 0
    total_samples = 0

    for images, labels in data_loader:
        images = images.to(device)
        labels = labels.to(device)

        optimizer.zero_grad()

        logits = model(images)
        loss = loss_function(logits, labels)

        loss.backward()
        optimizer.step()

        batch_size = labels.size(0)
        total_loss += loss.item() * batch_size
        correct_predictions += (logits.argmax(dim=1) == labels).sum().item()
        total_samples += batch_size

    average_loss = total_loss / total_samples
    accuracy = correct_predictions / total_samples

    return average_loss, accuracy


def evaluate(
    model: Module,
    data_loader: DataLoader,
    loss_function: CrossEntropyLoss,
    device: torch.device,
) -> tuple[float, float]:
    """Evaluate the model without updating its parameters."""

    model.eval()

    total_loss = 0.0
    correct_predictions = 0
    total_samples = 0

    with torch.inference_mode():
        for images, labels in data_loader:
            images = images.to(device)
            labels = labels.to(device)

            logits = model(images)
            loss = loss_function(logits, labels)

            batch_size = labels.size(0)
            total_loss += loss.item() * batch_size
            correct_predictions += (logits.argmax(dim=1) == labels).sum().item()
            total_samples += batch_size

    average_loss = total_loss / total_samples
    accuracy = correct_predictions / total_samples

    return average_loss, accuracy


def save_torchscript_model(model: Module, output_path: Path) -> None:
    """Export the trained model as TorchScript."""

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    model = model.to("cpu")
    model.eval()

    scripted_model = torch.jit.script(model)
    scripted_model.save(str(output_path))


@hydra.main(
    version_base=None,
    config_path="../../conf",
    config_name="config",
)
def main(cfg: DictConfig) -> None:
    """Train and export the Sentinel MNIST classifier."""

    torch.manual_seed(cfg.training.random_seed)
    np.random.seed(cfg.training.random_seed)

    task = Task.init(
        project_name=cfg.project.name,
        task_name=cfg.project.experiment_name,
    )

    resolved_config = OmegaConf.to_container(
        cfg,
        resolve=True,
    )
    task.connect(resolved_config)

    logger = task.get_logger()

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

    print("Loaded training configuration:")
    print(OmegaConf.to_yaml(cfg))
    print(f"Dataset ID: {dataset.id}")
    print(f"Dataset file: {dataset_file}")
    print("Preparing tensors with shared preprocessing...")

    tensor_dataset = load_tensor_dataset(dataset_file)

    training_loader, validation_loader = create_data_loaders(
        dataset=tensor_dataset,
        batch_size=cfg.training.batch_size,
        validation_ratio=cfg.training.validation_ratio,
        random_seed=cfg.training.random_seed,
    )

    requested_device = str(cfg.runtime.device)

    if requested_device == "cuda" and not torch.cuda.is_available():
        print("CUDA is unavailable. Falling back to CPU.")
        requested_device = "cpu"

    device = torch.device(requested_device)

    model = MNISTClassifier(
        num_classes=cfg.model.num_classes,
    ).to(device)

    loss_function = CrossEntropyLoss()
    optimizer = Adam(
        model.parameters(),
        lr=cfg.training.learning_rate,
    )

    print(f"Training on device: {device}")

    for epoch in range(1, cfg.training.epochs + 1):
        training_loss, training_accuracy = train_one_epoch(
            model=model,
            data_loader=training_loader,
            loss_function=loss_function,
            optimizer=optimizer,
            device=device,
        )

        validation_loss, validation_accuracy = evaluate(
            model=model,
            data_loader=validation_loader,
            loss_function=loss_function,
            device=device,
        )

        logger.report_scalar(
            title="Loss",
            series="Training",
            value=training_loss,
            iteration=epoch,
        )
        logger.report_scalar(
            title="Loss",
            series="Validation",
            value=validation_loss,
            iteration=epoch,
        )
        logger.report_scalar(
            title="Accuracy",
            series="Training",
            value=training_accuracy,
            iteration=epoch,
        )
        logger.report_scalar(
            title="Accuracy",
            series="Validation",
            value=validation_accuracy,
            iteration=epoch,
        )

        print(
            f"Epoch {epoch}/{cfg.training.epochs} | "
            f"train_loss={training_loss:.4f} | "
            f"train_accuracy={training_accuracy:.4f} | "
            f"validation_loss={validation_loss:.4f} | "
            f"validation_accuracy={validation_accuracy:.4f}"
        )

    save_torchscript_model(
        model=model,
        output_path=MODEL_OUTPUT_PATH,
    )

    task.upload_artifact(
        name="torchscript_model",
        artifact_object=MODEL_OUTPUT_PATH,
    )

    print(f"Model saved successfully: {MODEL_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
