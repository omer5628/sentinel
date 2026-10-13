
"""Tests for dynamic ClearML Serving preprocessing generation."""

import runpy
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

RENDER_SCRIPT = (
    PROJECT_ROOT / "scripts/render_serving_preprocess.py"
)

MNIST_TEMPLATE = (
    PROJECT_ROOT / "serving/preprocess/mnist.py"
)


def run_renderer(
    output_path: Path,
    model_version: str,
    template_path: Path = MNIST_TEMPLATE,
) -> subprocess.CompletedProcess[str]:
    """Execute the preprocessing renderer as a CLI command."""

    return subprocess.run(
        [
            sys.executable,
            str(RENDER_SCRIPT),
            "--template",
            str(template_path),
            "--output",
            str(output_path),
            "--model-version",
            model_version,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "model_version",
    [
        "retrain-35",
        "retrain-100",
        "v3",
        "model-2026-10-13",
    ],
)
def test_render_accepts_model_versions(
    tmp_path: Path,
    model_version: str,
) -> None:
    """Generate preprocessing code for supported model versions."""

    output_path = tmp_path / "preprocess.py"

    result = run_renderer(
        output_path,
        model_version,
    )

    assert result.returncode == 0, result.stderr
    assert output_path.is_file()

    content = output_path.read_text(encoding="utf-8")

    assert (
        f'MODEL_VERSION = "{model_version}"'
        in content
    )

    compile(content, str(output_path), "exec")


@pytest.mark.parametrize(
    "model_version",
    [
        "",
        "invalid version",
        "../invalid",
        "x" * 129,
    ],
)
def test_render_rejects_invalid_model_versions(
    tmp_path: Path,
    model_version: str,
) -> None:
    """Reject unsafe or invalid model version identifiers."""

    output_path = tmp_path / "preprocess.py"

    result = run_renderer(
        output_path,
        model_version,
    )

    assert result.returncode != 0
    assert not output_path.exists()


def test_render_preserves_original_template(
    tmp_path: Path,
) -> None:
    """Ensure rendering never modifies the source template."""

    original_content = MNIST_TEMPLATE.read_text(
        encoding="utf-8"
    )

    result = run_renderer(
        tmp_path / "preprocess.py",
        "retrain-35",
    )

    assert result.returncode == 0

    assert MNIST_TEMPLATE.read_text(
        encoding="utf-8"
    ) == original_content


def test_render_rejects_template_overwrite() -> None:
    """Prevent overwriting the source preprocessing template."""

    result = run_renderer(
        MNIST_TEMPLATE,
        "retrain-35",
    )

    assert result.returncode != 0


def test_rendered_preprocessing_contract(
    tmp_path: Path,
) -> None:
    """Verify the rendered adapter accepts images and returns predictions."""

    output_path = tmp_path / "preprocess.py"

    result = run_renderer(
        output_path,
        "retrain-35",
    )

    assert result.returncode == 0, result.stderr

    namespace = runpy.run_path(str(output_path))
    preprocess = namespace["Preprocess"]()

    pixels = np.zeros(
        (28, 28),
        dtype=np.float32,
    )

    prepared = preprocess.preprocess(
        {"pixels": pixels.tolist()},
        {},
    )

    assert prepared.shape == (1, 1, 28, 28)
    assert prepared.dtype == np.float32

    logits = np.zeros(
        (10,),
        dtype=np.float32,
    )
    logits[7] = 5.0

    prediction = preprocess.postprocess(
        logits,
        {},
    )

    assert prediction["predicted_class"] == 7
    assert 0.0 <= prediction["confidence"] <= 1.0
    assert prediction["model_version"] == "retrain-35"
    assert len(prediction["logits"]) == 10


def test_render_rejects_missing_placeholder(
    tmp_path: Path,
) -> None:
    """Reject templates without the model version assignment."""

    template_path = tmp_path / "invalid_template.py"
    template_path.write_text(
        "MODEL_VERSION = 'fixed'\n",
        encoding="utf-8",
    )

    output_path = tmp_path / "preprocess.py"

    result = run_renderer(
        output_path,
        "retrain-35",
        template_path,
    )

    assert result.returncode != 0
    assert not output_path.exists()
