"""Safely update one Canary model reference in a Helm values file.

This is a declarative Git-state update, not a Serving routing change.
The expected previous model ID is required to prevent stale writers.
"""

import argparse
import re
from pathlib import Path

MODEL_ID = re.compile(r"[0-9a-fA-F]{32}\Z")
CANARY_LINE = re.compile(
    r"^(  canaryReference:[ \t]*)(['\"]?)([0-9a-fA-F]{32})\2([ \t]*(?:#.*)?)$"
)


def _find_canary_line(text: str) -> tuple[list[str], int, re.Match[str], str]:
    """Locate one strictly formatted reference under the top-level model key."""

    lines = text.splitlines(keepends=True)
    model_headers = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == "model:"]
    if len(model_headers) != 1:
        raise ValueError("Expected exactly one top-level model block.")

    indices: list[tuple[int, re.Match[str], str]] = []
    for i in range(model_headers[0] + 1, len(lines)):
        raw = lines[i]
        body = raw.rstrip("\r\n")
        suffix = raw[len(body):]
        if body and not body[0].isspace() and not body.lstrip().startswith("#"):
            break
        if "canaryReference:" in body:
            match = CANARY_LINE.fullmatch(body)
            if match is None:
                raise ValueError("Unsupported format for model.canaryReference.")
            indices.append((i, match, suffix))

    if len(indices) != 1:
        raise ValueError("Expected exactly one model.canaryReference.")
    index, match, suffix = indices[0]
    return lines, index, match, suffix


def read_canary_reference(text: str) -> str:
    """Return the unique Canary model reference from a Helm values document."""

    _, _, match, _ = _find_canary_line(text)
    return match.group(3)


def update_canary_reference(text: str, expected_old: str, new_model: str) -> str:
    """Replace exactly one value in the top-level model block, preserving formatting."""

    for value in (expected_old, new_model):
        if MODEL_ID.fullmatch(value) is None:
            raise ValueError("Model references must be 32-character hex ClearML IDs.")

    lines, index, match, suffix = _find_canary_line(text)
    old_value = match.group(3)
    if old_value.lower() != expected_old.lower():
        raise ValueError(
            "Git Canary reference changed; refuse to overwrite stale state. "
            f"Expected {expected_old}, found {old_value}."
        )
    lines[index] = (
        f"{match.group(1)}{match.group(2)}{new_model}"
        f"{match.group(2)}{match.group(4)}{suffix}"
    )
    return "".join(lines)


def main() -> None:
    """Update the configured Git file after a verified Canary promotion."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--expected-old-id")
    parser.add_argument("--new-id")
    parser.add_argument("--read-current", action="store_true")
    args = parser.parse_args()

    before = args.file.read_text(encoding="utf-8")
    if args.read_current:
        if args.expected_old_id or args.new_id:
            parser.error("--read-current cannot be combined with update arguments.")
        print(read_canary_reference(before))
        return
    if not args.expected_old_id or not args.new_id:
        parser.error("Updating requires --expected-old-id and --new-id.")
    after = update_canary_reference(before, args.expected_old_id, args.new_id)
    if after != before:
        args.file.write_text(after, encoding="utf-8")
        print("Git Canary reference updated locally; not pushed yet.")
    else:
        print("Git Canary reference already points to the candidate.")


if __name__ == "__main__":
    main()
