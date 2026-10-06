from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class GoldenSample:
    """Represent one immutable sample from a golden evaluation dataset."""

    features: Any
    label: Hashable


class GoldenSetAdapter(Protocol):
    """Define how a model-specific dataset loads golden samples."""

    def load(
        self,
        dataset_path: Path,
    ) -> Sequence[GoldenSample]:
        """Load and return golden evaluation samples."""
        ...


class ModelAdapter(Protocol):
    """Define how a model is loaded and used for prediction."""

    def load(
        self,
        model_reference: str,
    ) -> Any:
        """Load a model from a model-specific reference."""
        ...

    def predict(
        self,
        model: Any,
        features: Any,
    ) -> Hashable:
        """Return one predicted label for one sample."""
        ...