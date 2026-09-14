import os
from dataclasses import dataclass

import numpy as np
import tritonclient.grpc as grpcclient
from tritonclient.grpc import InferenceServerClient
from tritonclient.utils import InferenceServerException

from sentinel.serving.inference_client import (
    DEFAULT_MODEL_NAME,
    DEFAULT_MODEL_VERSION,
    INPUT_DTYPE,
    INPUT_NAME,
    OUTPUT_NAME,
)


DEFAULT_TRITON_GRPC_URL = "localhost:8001"
DEFAULT_SHAP_BATCH_SIZE = 8
DEFAULT_SAMPLE_SHAPE = (1, 28, 28)


@dataclass(frozen=True)
class TritonDiagnosticsConfig:
    """Configuration for SHAP inference through Triton."""

    url: str
    model_name: str
    model_version: str
    batch_size: int
    sample_shape: tuple[int, ...]

    @classmethod
    def from_environment(
        cls,
    ) -> "TritonDiagnosticsConfig":
        """Load Triton diagnostics configuration from environment."""

        batch_size = int(
            os.getenv(
                "SHAP_TRITON_BATCH_SIZE",
                str(DEFAULT_SHAP_BATCH_SIZE),
            )
        )

        sample_shape = _parse_sample_shape(
            os.getenv(
                "SHAP_SAMPLE_SHAPE",
                ",".join(
                    str(dimension)
                    for dimension in DEFAULT_SAMPLE_SHAPE
                ),
            )
        )

        config = cls(
            url=os.getenv(
                "TRITON_GRPC_URL",
                DEFAULT_TRITON_GRPC_URL,
            ),
            model_name=os.getenv(
                "TRITON_MODEL_NAME",
                DEFAULT_MODEL_NAME,
            ),
            model_version=os.getenv(
                "TRITON_MODEL_VERSION",
                DEFAULT_MODEL_VERSION,
            ),
            batch_size=batch_size,
            sample_shape=sample_shape,
        )

        config.validate()

        return config

    def validate(self) -> None:
        """Validate Triton diagnostics configuration."""

        if not self.url.strip():
            raise ValueError(
                "Triton URL cannot be empty."
            )

        if not self.model_name.strip():
            raise ValueError(
                "Triton model name cannot be empty."
            )

        if not self.model_version.strip():
            raise ValueError(
                "Triton model version cannot be empty."
            )

        if self.batch_size <= 0:
            raise ValueError(
                "SHAP Triton batch size must be greater than zero."
            )

        if self.batch_size > DEFAULT_SHAP_BATCH_SIZE:
            raise ValueError(
                "SHAP Triton batch size cannot exceed "
                f"{DEFAULT_SHAP_BATCH_SIZE}."
            )

        if not self.sample_shape:
            raise ValueError(
                "Triton sample shape cannot be empty."
            )

        if any(
            dimension <= 0
            for dimension in self.sample_shape
        ):
            raise ValueError(
                "Triton sample shape dimensions "
                "must be greater than zero."
            )


def _parse_sample_shape(
    value: str,
) -> tuple[int, ...]:
    """Parse a comma-separated input shape."""

    try:
        shape = tuple(
            int(part.strip())
            for part in value.split(",")
            if part.strip()
        )
    except ValueError as error:
        raise ValueError(
            "SHAP_SAMPLE_SHAPE must contain "
            "comma-separated integers."
        ) from error

    if not shape:
        raise ValueError(
            "SHAP_SAMPLE_SHAPE cannot be empty."
        )

    return shape


class TritonBatchPredictor:
    """Run batched model predictions for SHAP diagnostics."""

    def __init__(
        self,
        config: TritonDiagnosticsConfig,
    ) -> None:
        config.validate()

        self.config = config

        self._client = InferenceServerClient(
            url=config.url,
        )

    def is_ready(self) -> bool:
        """Return whether Triton and the configured model are ready."""

        try:
            return bool(
                self._client.is_server_live()
                and self._client.is_server_ready()
                and self._client.is_model_ready(
                    model_name=self.config.model_name,
                    model_version=self.config.model_version,
                )
            )
        except InferenceServerException:
            return False

    def predict_probabilities(
        self,
        feature_matrix: np.ndarray,
    ) -> np.ndarray:
        """Return class probabilities for a flat feature matrix."""

        normalized_features = (
            self._validate_feature_matrix(
                feature_matrix
            )
        )

        probability_batches: list[np.ndarray] = []

        for start_index in range(
            0,
            normalized_features.shape[0],
            self.config.batch_size,
        ):
            end_index = min(
                start_index + self.config.batch_size,
                normalized_features.shape[0],
            )

            flat_batch = normalized_features[
                start_index:end_index
            ]

            input_batch = flat_batch.reshape(
                (
                    flat_batch.shape[0],
                    *self.config.sample_shape,
                )
            )

            logits = self._infer_batch(
                input_batch
            )

            probabilities = self._softmax(
                logits
            )

            probability_batches.append(
                probabilities
            )

        return np.concatenate(
            probability_batches,
            axis=0,
        )

    def _validate_feature_matrix(
        self,
        feature_matrix: np.ndarray,
    ) -> np.ndarray:
        """Validate and normalize a SHAP feature matrix."""

        if not isinstance(
            feature_matrix,
            np.ndarray,
        ):
            raise TypeError(
                "feature_matrix must be a NumPy array."
            )

        if feature_matrix.ndim != 2:
            raise ValueError(
                "feature_matrix must have shape "
                "(samples, features)."
            )

        if feature_matrix.shape[0] == 0:
            raise ValueError(
                "feature_matrix must contain at least one sample."
            )

        expected_feature_count = int(
            np.prod(
                self.config.sample_shape
            )
        )

        if (
            feature_matrix.shape[1]
            != expected_feature_count
        ):
            raise ValueError(
                "Invalid feature count: "
                f"expected {expected_feature_count}, "
                f"received {feature_matrix.shape[1]}."
            )

        normalized_features = feature_matrix.astype(
            np.float32,
            copy=False,
        )

        if not np.isfinite(
            normalized_features
        ).all():
            raise ValueError(
                "feature_matrix contains non-finite values."
            )

        return np.ascontiguousarray(
            normalized_features
        )

    def _infer_batch(
        self,
        input_batch: np.ndarray,
    ) -> np.ndarray:
        """Send one batch to Triton and return raw logits."""

        triton_input = grpcclient.InferInput(
            INPUT_NAME,
            input_batch.shape,
            INPUT_DTYPE,
        )

        triton_input.set_data_from_numpy(
            input_batch
        )

        requested_output = (
            grpcclient.InferRequestedOutput(
                OUTPUT_NAME
            )
        )

        try:
            response = self._client.infer(
                model_name=self.config.model_name,
                model_version=self.config.model_version,
                inputs=[triton_input],
                outputs=[requested_output],
            )
        except InferenceServerException as error:
            raise RuntimeError(
                "Triton batch inference request failed."
            ) from error

        if response is None:
            raise RuntimeError(
                "Triton returned an empty inference response."
            )

        logits = response.as_numpy(
            OUTPUT_NAME
        )

        if logits is None:
            raise RuntimeError(
                "Triton response does not contain "
                f"output '{OUTPUT_NAME}'."
            )

        logits_array = np.asarray(
            logits,
            dtype=np.float32,
        )

        if logits_array.ndim != 2:
            raise RuntimeError(
                "Triton returned an invalid output shape: "
                f"{logits_array.shape}."
            )

        if (
            logits_array.shape[0]
            != input_batch.shape[0]
        ):
            raise RuntimeError(
                "Triton returned a different number "
                "of predictions than input samples."
            )

        if logits_array.shape[1] == 0:
            raise RuntimeError(
                "Triton returned no model outputs."
            )

        return logits_array

    @staticmethod
    def _softmax(
        logits: np.ndarray,
    ) -> np.ndarray:
        """Convert model logits into class probabilities."""

        shifted_logits = (
            logits
            - np.max(
                logits,
                axis=1,
                keepdims=True,
            )
        )

        exponentials = np.exp(
            shifted_logits
        )

        probabilities = (
            exponentials
            / np.sum(
                exponentials,
                axis=1,
                keepdims=True,
            )
        )

        return np.asarray(
            probabilities,
            dtype=np.float32,
        )

    def close(self) -> None:
        """Close the Triton client."""

        close_method = getattr(
            self._client,
            "close",
            None,
        )

        if callable(close_method):
            close_method()