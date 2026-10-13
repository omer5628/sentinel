"""Smoke-test a specific ClearML Serving version before Canary promotion.

The request goes directly to the versioned model endpoint, never to the
Canary router. This tool does not mutate model or routing configuration.
"""

import argparse
import math
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from omegaconf import OmegaConf


MODEL_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def _filled_array(shape: list[int], fill_value: float) -> Any:
    """Build a nested numeric sample with the configured dimensions."""
    if not shape:
        return fill_value
    return [_filled_array(shape[1:], fill_value) for _ in range(shape[0])]


def load_smoke_config(config_path: Path) -> tuple[str, str, dict[str, Any], int]:
    """Load the model-specific smoke request and expected class count."""
    cfg = OmegaConf.load(config_path)
    base_endpoint = str(cfg.endpoints.base)
    field = str(cfg.smokeTest.requestField)
    shape = list(cfg.smokeTest.sampleShape)
    value = float(cfg.smokeTest.sampleValue)
    output_size = list(cfg.output.size)

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", base_endpoint):
        raise ValueError("Invalid model endpoint name.")
    if not field or not field.isidentifier():
        raise ValueError("Invalid smoke-test request field.")
    if (not shape or len(shape) > 6 or any(
        isinstance(dim, bool) or not isinstance(dim, int) or dim < 1
        for dim in shape
    )):
        raise ValueError("Smoke-test sample shape must use positive integers.")
    if math.prod(shape) > 100_000:
        raise ValueError("Smoke-test sample contains too many values.")
    if not math.isfinite(value):
        raise ValueError("Smoke-test sample value must be finite.")
    if (not output_size or not isinstance(output_size[-1], int)
            or output_size[-1] < 1):
        raise ValueError("Invalid expected output class count.")

    return base_endpoint, field, {field: _filled_array(shape, value)}, output_size[-1]


def make_endpoint_url(inference_base_url: str, endpoint: str, version: int) -> str:
    """Build a version-specific URL without touching the Canary router."""
    parsed = urlsplit(inference_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Inference base URL must use HTTP(S) and have a host.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Inference base URL must not contain a path or query.")
    if version < 1:
        raise ValueError("Serving version must be positive.")
    return f"{inference_base_url.rstrip('/')}/serve/{endpoint}/{version}"


def verify_prediction(
    response: Any,
    expected_model_version: str,
    expected_class_count: int,
) -> None:
    """Validate the Sentinel prediction response and model identity."""
    if not isinstance(response, Mapping):
        raise ValueError("Serving response must be a JSON object.")
    if response.get("model_version") != expected_model_version:
        raise ValueError("Serving returned an unexpected model version.")

    predicted_class = response.get("predicted_class")
    if (isinstance(predicted_class, bool)
            or not isinstance(predicted_class, int)
            or not 0 <= predicted_class < expected_class_count):
        raise ValueError("Serving returned an invalid predicted class.")

    confidence = response.get("confidence")
    if (isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not math.isfinite(confidence)
            or not 0.0 <= confidence <= 1.0):
        raise ValueError("Serving returned an invalid confidence.")

    logits = response.get("logits")
    if logits is not None and (
        not isinstance(logits, list)
        or len(logits) != expected_class_count
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in logits
        )
    ):
        raise ValueError("Serving returned invalid logits.")


def smoke_test(
    config_path: Path,
    inference_base_url: str,
    serving_version: int,
    model_version: str,
    attempts: int = 12,
    retry_seconds: float = 5.0,
    timeout_seconds: float = 10.0,
) -> str:
    """Wait for a specific model version to answer a valid inference."""
    if MODEL_VERSION_PATTERN.fullmatch(model_version) is None:
        raise ValueError("Invalid model version.")
    if attempts < 1 or retry_seconds < 0 or timeout_seconds <= 0:
        raise ValueError("Invalid smoke-test retry or timeout settings.")

    endpoint, _, payload, class_count = load_smoke_config(config_path)
    url = make_endpoint_url(inference_base_url, endpoint, serving_version)

    with httpx.Client(timeout=timeout_seconds) as client:
        for attempt in range(1, attempts + 1):
            try:
                result = client.post(url, json=payload)
                result.raise_for_status()
                verify_prediction(result.json(), model_version, class_count)
                print(f"Inference verified: {endpoint}/{serving_version} ({model_version})")
                return url
            except (httpx.HTTPError, ValueError) as error:
                if attempt == attempts:
                    raise RuntimeError(
                        f"Serving smoke test failed after {attempts} attempts: {url}"
                    ) from error
                print(f"Inference not ready ({attempt}/{attempts}): {error}")
                time.sleep(retry_seconds)

    raise AssertionError("Unreachable smoke-test state.")


def main() -> None:
    """Run the read-only model inference verification CLI."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--inference-base-url", required=True)
    parser.add_argument("--serving-version", type=int, required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--attempts", type=int, default=12)
    parser.add_argument("--retry-seconds", type=float, default=5.0)
    args = parser.parse_args()
    smoke_test(
        config_path=args.config,
        inference_base_url=args.inference_base_url,
        serving_version=args.serving_version,
        model_version=args.model_version,
        attempts=args.attempts,
        retry_seconds=args.retry_seconds,
    )


if __name__ == "__main__":
    main()
