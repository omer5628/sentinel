#!/usr/bin/env python3
"""Back up full Sentinel MNIST CSV to GCS before replacing the local CSV.

Uses only Python standard library and an existing Google Cloud CLI login.
The original file is never replaced before a byte-for-byte verified GCS backup.
"""

import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_PIXELS = 784
EXPECTED_ROWS = 70_000
CLASSES = tuple(str(i) for i in range(10))
SAMPLES_PER_CLASS = 100


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cloud(*args: str) -> str:
    result = subprocess.run(
        ["gcloud", "storage", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"gcloud storage {args[0]} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def holdout_indices(root: Path) -> set[int]:
    path = root / "data" / "golden_set_manifest.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected immutable holdout manifest: {path}"
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    samples = payload.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("Golden-set holdout manifest is empty or invalid")
    ids = {sample["source_index"] for sample in samples}
    if any(type(x) is not int or x < 0 for x in ids):
        raise ValueError("Invalid holdout source_index in manifest")
    return ids


def create_sample(src: Path, dst: Path, excluded: set[int], seed: int) -> tuple[int, list[int]]:
    rngs = {label: random.Random(seed + int(label)) for label in CLASSES}
    seen = Counter()
    sample: dict[str, list[tuple[int, list[str]]]] = {
        label: [] for label in CLASSES
    }
    rows = 0
    with src.open("r", encoding="utf-8", newline="") as inp:
        reader = csv.reader(inp)
        header = next(reader)
        expected_header = [f"pixel{i}" for i in range(1, EXPECTED_PIXELS + 1)] + ["label"]
        if header != expected_header:
            raise ValueError("Unexpected MNIST CSV schema; refusing to modify it")
        for index, row in enumerate(reader):
            rows += 1
            if len(row) != len(header):
                raise ValueError(f"Invalid field count on source row {index + 2}")
            label = row[-1]
            if label not in sample:
                raise ValueError(f"Invalid MNIST label {label!r} on source row {index + 2}")
            if index in excluded:
                continue
            seen[label] += 1
            choice = sample[label]
            if len(choice) < SAMPLES_PER_CLASS:
                choice.append((index, row))
            else:
                replacement = rngs[label].randrange(seen[label])
                if replacement < SAMPLES_PER_CLASS:
                    choice[replacement] = (index, row)

    if rows != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS} source rows; found {rows}; no changes made")
    for label in CLASSES:
        if len(sample[label]) != SAMPLES_PER_CLASS:
            raise ValueError(f"Not enough eligible samples for label {label}")
    combined = sorted((entry for group in sample.values() for entry in group), key=lambda item: item[0])
    indices = [index for index, _ in combined]
    if len(indices) != 1000 or set(indices).intersection(excluded):
        raise AssertionError("Sampling or holdout exclusion failed")
    with dst.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(row for _, row in combined)
        out.flush()
        os.fsync(out.fileno())
    with dst.open("r", encoding="utf-8", newline="") as check:
        actual = sum(1 for _ in csv.reader(check)) - 1
    if actual != 1000:
        raise AssertionError(f"Sample row-count validation failed: {actual}")
    return rows, indices


def backup_to_gcs(src: Path, gcs_uri: str, expected_hash: str, verify_dir: Path) -> None:
    if shutil.which("gcloud") is None:
        raise RuntimeError("gcloud CLI is not installed; local dataset was not modified")
    # Never overwrite an existing object (including concurrent uploads).
    existing = subprocess.run(
        ["gcloud", "storage", "objects", "describe", gcs_uri],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    if existing.returncode != 0:
        print(f"Uploading unchanged full dataset to: {gcs_uri}", flush=True)
        cloud("cp", "--if-generation-match=0", str(src), gcs_uri)
    else:
        print(f"GCS object already exists; verifying: {gcs_uri}", flush=True)
    # Download and hash the actual stored object, not just upload logs/metadata.
    downloaded = verify_dir / "gcs-full-mnist-verify.csv"
    print("Downloading GCS backup for byte-for-byte SHA256 verification...", flush=True)
    cloud("cp", gcs_uri, str(downloaded))
    received_hash = sha256(downloaded)
    if received_hash != expected_hash:
        raise RuntimeError("GCS backup verification FAILED; local dataset was NOT modified")
    print(f"PASS: GCS backup SHA256 verified: {received_hash}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--gcs-prefix", default="", help="Existing GCS location: gs://BUCKET/path")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="Sample and validate, but do not upload or replace")
    args = parser.parse_args()

    root = args.project_root.expanduser().resolve()
    src = root / "data" / "mnist.csv"
    if src.is_symlink() or not src.is_file():
        raise ValueError(f"Expected a regular MNIST CSV: {src}")
    original_hash = sha256(src)
    original_size = src.stat().st_size
    excluded = holdout_indices(root)

    with tempfile.TemporaryDirectory(prefix="mnist-trim-", dir=src.parent) as staging:
        temp = Path(staging)
        sample_path = temp / "mnist.csv"
        total, indices = create_sample(src, sample_path, excluded, args.seed)
        print(f"PASS: Source: {total:,} images, {original_size:,} bytes")
        print(f"PASS: Sample: 1,000 images (100 per class), {sample_path.stat().st_size:,} bytes")
        print(f"PASS: Excluded {len(excluded)} immutable golden-set source indices")
        print(f"Source SHA256: {original_hash}")

        if args.dry_run:
            print("DRY RUN: No GCS upload and no project file modifications")
            return

        prefix = args.gcs_prefix.rstrip("/")
        if not re.fullmatch(r"gs://[a-zA-Z0-9][a-zA-Z0-9._-]{2,61}(?:/[^\s]+)?", prefix):
            raise ValueError("Specify an existing GCS prefix, e.g. --gcs-prefix gs://my-bucket/sentinel/datasets/full")
        uri = f"{prefix}/mnist-70000-sha256-{original_hash[:16]}.csv"
        backup_to_gcs(src, uri, original_hash, temp)
        if sha256(src) != original_hash or src.stat().st_size != original_size:
            raise RuntimeError("Source changed during upload; refusing to replace it")

        provenance = {
            "source_file": "data/mnist.csv",
            "source_rows": total,
            "source_sha256": original_hash,
            "source_gcs_uri": uri,
            "sample_rows": 1000,
            "sample_sha256": sha256(sample_path),
            "selection": "deterministic per-class reservoir, excluding golden-set source indices",
            "seed": args.seed,
            "class_counts": {label: 100 for label in CLASSES},
            "source_indices": indices,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "clearml_dataset_modified": False,
        }
        manifest_target = root / "data" / "mnist_1000_provenance.json"
        manifest_tmp = temp / "mnist_1000_provenance.json"
        manifest_tmp.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
        # Manifest is committed to disk first; then replace the local dataset atomically.
        os.replace(manifest_tmp, manifest_target)
        os.replace(sample_path, src)
        print(f"PASS: Local project now has 1,000 images: {src}")
        print(f"PASS: Full 70,000-image dataset backed up in GCS: {uri}")
        print(f"PASS: Sample provenance: {manifest_target}")
        print("NOTE: ClearML dataset 1.0.0 and golden_set were not changed")


if __name__ == "__main__":
    main()
