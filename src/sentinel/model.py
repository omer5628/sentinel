import torch
from torch import Tensor
from torch.nn import Conv2d, Dropout, Flatten, Linear, MaxPool2d, Module, ReLU


class MNISTClassifier(Module):
    """Classify normalized 28x28 grayscale MNIST images."""

    def __init__(self, num_classes: int = 10) -> None:
        super().__init__()

        self.features = torch.nn.Sequential(
            Conv2d(
                in_channels=1,
                out_channels=32,
                kernel_size=3,
                padding=1,
            ),
            ReLU(),
            MaxPool2d(kernel_size=2),
            Conv2d(
                in_channels=32,
                out_channels=64,
                kernel_size=3,
                padding=1,
            ),
            ReLU(),
            MaxPool2d(kernel_size=2),
        )

        self.classifier = torch.nn.Sequential(
            Flatten(),
            Linear(64 * 7 * 7, 128),
            ReLU(),
            Dropout(p=0.25),
            Linear(128, num_classes),
        )

    def forward(self, inputs: Tensor) -> Tensor:
        """Return class logits for a batch of images."""

        features = self.features(inputs)
        return self.classifier(features)
