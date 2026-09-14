import os
from dataclasses import dataclass
from typing import Protocol

import numpy as np
import shap


DEFAULT_SHAP_NSAMPLES = 128
DEFAULT_TOP_FEATURE_COUNT = 3
DEFAULT_L1_FEATURE_COUNT = 3
DEFAULT_RANDOM_SEED = 42


class ProbabilityPredictor(Protocol):
    """Describe the prediction interface required by SHAP."""

    def predict_probabilities(
        self,
        feature_matrix: np.ndarray,
    ) -> np.ndarray:
        """Return class probabilities for a feature matrix."""
        ...


@dataclass(frozen=True)
class KernelShapConfig:
    """Configuration for lightweight Kernel SHAP diagnostics."""

    nsamples: int
    top_feature_count: int
    l1_feature_count: int
    random_seed: int

    @classmethod
    def from_environment(
        cls,
    ) -> "KernelShapConfig":
        """Load Kernel SHAP configuration from environment."""

        config = cls(
            nsamples=int(
                os.getenv(
                    "SHAP_NSAMPLES",
                    str(DEFAULT_SHAP_NSAMPLES),
                )
            ),
            top_feature_count=int(
                os.getenv(
                    "SHAP_TOP_FEATURES",
                    str(DEFAULT_TOP_FEATURE_COUNT),
                )
            ),
            l1_feature_count=int(
                os.getenv(
                    "SHAP_L1_FEATURES",
                    str(DEFAULT_L1_FEATURE_COUNT),
                )
            ),
            random_seed=int(
                os.getenv(
                    "SHAP_RANDOM_SEED",
                    str(DEFAULT_RANDOM_SEED),
                )
            ),
        )

        config.validate()

        return config

    def validate(self) -> None:
        """Validate Kernel SHAP configuration."""

        if self.nsamples <= 0:
            raise ValueError(
                "SHAP nsamples must be greater than zero."
            )

        if self.top_feature_count <= 0:
            raise ValueError(
                "SHAP top feature count must be greater than zero."
            )

        if self.l1_feature_count <= 0:
            raise ValueError(
                "SHAP L1 feature count must be greater than zero."
            )

        if (
            self.l1_feature_count
            < self.top_feature_count
        ):
            raise ValueError(
                "SHAP L1 feature count cannot be smaller "
                "than the requested top feature count."
            )

        if self.random_seed < 0:
            raise ValueError(
                "SHAP random seed must be non-negative."
            )


@dataclass(frozen=True)
class FeatureContribution:
    """Represent one important feature from a SHAP explanation."""

    feature_index: int
    feature_name: str
    mean_absolute_shap: float


@dataclass(frozen=True)
class KernelShapResult:
    """Represent aggregated SHAP diagnostics for a drift alert."""

    alert_class: int
    expected_value: float
    explained_sample_count: int
    feature_count: int
    top_features: tuple[FeatureContribution, ...]


def validate_feature_matrices(
    background_matrix: np.ndarray,
    drift_matrix: np.ndarray,
) -> None:
    """Validate background and drift matrices."""

    for name, matrix in (
        ("background", background_matrix),
        ("drift", drift_matrix),
    ):
        if not isinstance(
            matrix,
            np.ndarray,
        ):
            raise TypeError(
                f"{name} matrix must be a NumPy array."
            )

        if matrix.ndim != 2:
            raise ValueError(
                f"{name} matrix must have shape "
                "(samples, features)."
            )

        if matrix.shape[0] == 0:
            raise ValueError(
                f"{name} matrix must contain at least one sample."
            )

        if matrix.shape[1] == 0:
            raise ValueError(
                f"{name} matrix must contain at least one feature."
            )

        if not np.isfinite(
            matrix
        ).all():
            raise ValueError(
                f"{name} matrix contains non-finite values."
            )

    if (
        background_matrix.shape[1]
        != drift_matrix.shape[1]
    ):
        raise ValueError(
            "Background and drift matrices contain "
            "different feature counts."
        )


def build_feature_names(
    feature_count: int,
    sample_shape: tuple[int, ...],
) -> tuple[str, ...]:
    """Build generic names for flattened model features."""

    expected_feature_count = int(
        np.prod(
            sample_shape
        )
    )

    if expected_feature_count != feature_count:
        return tuple(
            f"feature_{index}"
            for index in range(feature_count)
        )

    if len(sample_shape) != 3:
        return tuple(
            f"feature_{index}"
            for index in range(feature_count)
        )

    channels, height, width = sample_shape

    feature_names: list[str] = []

    pixels_per_channel = (
        height * width
    )

    for index in range(feature_count):
        channel = (
            index // pixels_per_channel
        )

        pixel_index = (
            index % pixels_per_channel
        )

        row = (
            pixel_index // width
        )

        column = (
            pixel_index % width
        )

        if channels == 1:
            feature_name = (
                f"pixel_{row}_{column}"
            )
        else:
            feature_name = (
                f"channel_{channel}_"
                f"pixel_{row}_{column}"
            )

        feature_names.append(
            feature_name
        )

    return tuple(
        feature_names
    )


def run_kernel_shap(
    predictor: ProbabilityPredictor,
    background_matrix: np.ndarray,
    drift_matrix: np.ndarray,
    alert_class: int,
    sample_shape: tuple[int, ...],
    config: KernelShapConfig,
) -> KernelShapResult:
    """Explain drift samples relative to historical background data."""

    config.validate()

    validate_feature_matrices(
        background_matrix=background_matrix,
        drift_matrix=drift_matrix,
    )

    if alert_class < 0:
        raise ValueError(
            "alert_class must be non-negative."
        )

    background = np.ascontiguousarray(
        background_matrix,
        dtype=np.float32,
    )

    drift = np.ascontiguousarray(
        drift_matrix,
        dtype=np.float32,
    )

    feature_count = int(
        drift.shape[1]
    )

    feature_names = build_feature_names(
        feature_count=feature_count,
        sample_shape=sample_shape,
    )

    explainer = shap.KernelExplainer(
        model=predictor.predict_probabilities,
        data=background,
        feature_names=list(
            feature_names
        ),
        link="identity",
    )

    random_state = np.random.get_state()

    try:
        np.random.seed(
            config.random_seed
        )

        shap_values = explainer.shap_values(
            drift,
            nsamples=config.nsamples,
            l1_reg=(
                "num_features"
                f"({config.l1_feature_count})"
            ),
            silent=True,
        )

    finally:
        np.random.set_state(
            random_state
        )

    shap_array = np.asarray(
        shap_values,
        dtype=np.float64,
    )

    if shap_array.ndim != 3:
        raise RuntimeError(
            "Kernel SHAP returned an unexpected shape: "
            f"{shap_array.shape}."
        )

    if (
        shap_array.shape[0]
        != drift.shape[0]
    ):
        raise RuntimeError(
            "Kernel SHAP returned an unexpected "
            "number of explained samples."
        )

    if (
        shap_array.shape[1]
        != feature_count
    ):
        raise RuntimeError(
            "Kernel SHAP returned an unexpected "
            "number of features."
        )

    output_count = int(
        shap_array.shape[2]
    )

    if alert_class >= output_count:
        raise ValueError(
            "alert_class is outside the model output range: "
            f"class={alert_class}, "
            f"outputs={output_count}."
        )

    target_shap_values = (
        shap_array[
            :,
            :,
            alert_class,
        ]
    )

    mean_absolute_shap = np.mean(
        np.abs(
            target_shap_values
        ),
        axis=0,
    )

    top_feature_count = min(
        config.top_feature_count,
        feature_count,
    )

    top_indices = np.argsort(
        -mean_absolute_shap,
        kind="stable",
    )[
        :top_feature_count
    ]

    top_features = tuple(
        FeatureContribution(
            feature_index=int(
                feature_index
            ),
            feature_name=feature_names[
                int(feature_index)
            ],
            mean_absolute_shap=float(
                mean_absolute_shap[
                    int(feature_index)
                ]
            ),
        )
        for feature_index in top_indices
    )

    expected_values = np.asarray(
        explainer.expected_value,
        dtype=np.float64,
    ).reshape(-1)

    if alert_class >= expected_values.size:
        raise RuntimeError(
            "Kernel SHAP expected value does not "
            "contain the alert class."
        )

    return KernelShapResult(
        alert_class=alert_class,
        expected_value=float(
            expected_values[
                alert_class
            ]
        ),
        explained_sample_count=int(
            drift.shape[0]
        ),
        feature_count=feature_count,
        top_features=top_features,
    )


def print_kernel_shap_result(
    result: KernelShapResult,
) -> None:
    """Print SHAP diagnostic results in a stable log format."""

    print(
        f"shap_alert_class={result.alert_class}"
    )

    print(
        "shap_explained_samples="
        f"{result.explained_sample_count}"
    )

    print(
        f"shap_feature_count={result.feature_count}"
    )

    print(
        "shap_expected_value="
        f"{result.expected_value:.8f}"
    )

    for rank, contribution in enumerate(
        result.top_features,
        start=1,
    ):
        print(
            f"shap_top_feature_{rank}="
            f"{contribution.feature_name}"
        )

        print(
            f"shap_top_feature_{rank}_index="
            f"{contribution.feature_index}"
        )

        print(
            f"shap_top_feature_{rank}_mean_abs="
            f"{contribution.mean_absolute_shap:.8f}"
        )
