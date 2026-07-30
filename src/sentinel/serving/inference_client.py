import os
from dataclasses import dataclass

import numpy as np
import tritonclient.grpc as grpcclient
from tritonclient.grpc import InferenceServerClient
from tritonclient.utils import InferenceServerException


DEFAULT_TRITON_URL = "localhost:8001"
DEFAULT_MODEL_NAME = "sentinel-mnist_1"
DEFAULT_MODEL_VERSION = "1"

INPUT_NAME = "INPUT__0"
OUTPUT_NAME = "OUTPUT__0"
INPUT_DTYPE = "FP32"

EXPECTED_FEATURE_SHAPE = (1, 1, 28, 28)
EXPECTED_OUTPUT_SHAPE = (1, 10)


@dataclass(frozen=True)
class PredictionResult:
    """Represent a prediction returned by Triton."""

    predicted_class: int
    confidence: float
    logits: np.ndarray


class TritonInferenceClient:
    """Send MNIST inference requests to Triton over gRPC."""

    def __init__(
        self,
        url: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        self.url = url or os.getenv(
            "TRITON_GRPC_URL",
            DEFAULT_TRITON_URL,
        )
        self.model_name = model_name or os.getenv(
            "TRITON_MODEL_NAME",
            DEFAULT_MODEL_NAME,
        )
        self.model_version = model_version or os.getenv(
            "TRITON_MODEL_VERSION",
            DEFAULT_MODEL_VERSION,
        )

        self._client = InferenceServerClient(
            url=self.url,
        )

    def is_ready(self) -> bool:
        """Return whether Triton and the configured model are ready."""

        try:
            server_live = bool(
                self._client.is_server_live()
            )
            server_ready = bool(
                self._client.is_server_ready()
            )
            model_ready = bool(
                self._client.is_model_ready(
                    model_name=self.model_name,
                    model_version=self.model_version,
                )
            )

            return (
                server_live
                and server_ready
                and model_ready
            )
        except InferenceServerException:
            return False

    def predict(
        self,
        feature_array: np.ndarray,
    ) -> PredictionResult:
        """Run inference and return class, confidence, and raw logits."""

        normalized_feature = self._validate_feature(
            feature_array
        )

        triton_input = grpcclient.InferInput(
            INPUT_NAME,
            normalized_feature.shape,
            INPUT_DTYPE,
        )
        triton_input.set_data_from_numpy(
            normalized_feature
        )

        requested_output = grpcclient.InferRequestedOutput(
            OUTPUT_NAME,
        )

        try:
            response = self._client.infer(
                model_name=self.model_name,
                model_version=self.model_version,
                inputs=[triton_input],
                outputs=[requested_output],
            )
        except InferenceServerException as error:
            raise RuntimeError(
                "Triton inference request failed."
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
                f"Triton response does not contain output "
                f"'{OUTPUT_NAME}'."
            )

        if logits.shape != EXPECTED_OUTPUT_SHAPE:
            raise RuntimeError(
                "Triton returned an invalid output shape: "
                f"expected {EXPECTED_OUTPUT_SHAPE}, "
                f"received {logits.shape}."
            )

        probabilities = self._softmax(
            logits
        )
        predicted_class = int(
            np.argmax(
                probabilities,
                axis=1,
            )[0]
        )
        confidence = float(
            probabilities[
                0,
                predicted_class,
            ]
        )

        return PredictionResult(
            predicted_class=predicted_class,
            confidence=confidence,
            logits=logits,
        )

    def close(self) -> None:
        """Close the Triton gRPC client."""

        close_method = getattr(
            self._client,
            "close",
            None,
        )

        if callable(close_method):
            close_method()

    @staticmethod
    def _validate_feature(
        feature_array: np.ndarray,
    ) -> np.ndarray:
        """Validate and normalize the feature sent to Triton."""

        if not isinstance(
            feature_array,
            np.ndarray,
        ):
            raise TypeError(
                "feature_array must be a NumPy array."
            )

        if feature_array.shape != EXPECTED_FEATURE_SHAPE:
            raise ValueError(
                "Invalid feature shape: "
                f"expected {EXPECTED_FEATURE_SHAPE}, "
                f"received {feature_array.shape}."
            )

        if feature_array.dtype != np.float32:
            feature_array = feature_array.astype(
                np.float32,
                copy=False,
            )

        if not np.isfinite(
            feature_array
        ).all():
            raise ValueError(
                "Feature array contains non-finite values."
            )

        return np.ascontiguousarray(
            feature_array
        )

    @staticmethod
    def _softmax(
        logits: np.ndarray,
    ) -> np.ndarray:
        """Convert model logits into probabilities."""

        shifted_logits = logits - np.max(
            logits,
            axis=1,
            keepdims=True,
        )
        exponentials = np.exp(
            shifted_logits
        )

        return exponentials / np.sum(
            exponentials,
            axis=1,
            keepdims=True,
        )