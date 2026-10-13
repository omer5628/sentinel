
"""Render a model-specific preprocessing template for serving."""

import argparse
import json
import re
from pathlib import Path


MODEL_VERSION_ASSIGNMENT = (
    'MODEL_VERSION = "__SENTINEL_MODEL_VERSION__"'
)

MODEL_VERSION_PATTERN = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"
)


def render_preprocess(
    template_path: Path,
    output_path: Path,
    model_version: str,
) -> None:
    """Render a preprocessing adapter with a validated model version."""

    if MODEL_VERSION_PATTERN.fullmatch(model_version) is None:
        raise ValueError(
            "Model version must contain 1-128 characters "
            "using letters, numbers, dots, underscores or hyphens."
        )

    if template_path.resolve() == output_path.resolve():
        raise ValueError(
            "Output path must differ from the source template."
        )

    template = template_path.read_text(
        encoding="utf-8"
    )

    if template.count(MODEL_VERSION_ASSIGNMENT) != 1:
        raise ValueError(
            "Expected exactly one model version assignment "
            "in the preprocessing template."
        )

    rendered = template.replace(
        MODEL_VERSION_ASSIGNMENT,
        f"MODEL_VERSION = {json.dumps(model_version)}",
        1,
    )

    compile(
        rendered,
        str(output_path),
        "exec",
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        rendered,
        encoding="utf-8",
    )


def main() -> None:
    """Parse arguments and render the preprocessing adapter."""

    parser = argparse.ArgumentParser(
        description="Render a ClearML Serving preprocessing adapter."
    )

    parser.add_argument(
        "--template",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--model-version",
        required=True,
    )

    args = parser.parse_args()

    render_preprocess(
        template_path=args.template,
        output_path=args.output,
        model_version=args.model_version,
    )

    print(
        f"Preprocessing rendered successfully: {args.output}"
    )


if __name__ == "__main__":
    main()
