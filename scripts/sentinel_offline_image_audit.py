#!/usr/bin/env python3
"""Read-only audit of active container images rendered by Sentinel Helm charts.

The profiles mirror the current Sentinel dev/prod deployment and the optional
ClearML Serving Kafka/KRaft profile. No Kubernetes resources are created.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent if Path(__file__).parent.name == "scripts" else Path.cwd()
SENTINEL = ROOT / "charts/sentinel"
SERVING = ROOT / "charts/vendor/clearml-serving"
SERVING_VALUES = ROOT / "serving/values-sentinel.yaml"
KRAFT_VALUES = ROOT / "serving/clearml-serving-kraft-values.yaml"

MISSING_IMAGES = {
    "bitnami/bitnami-shell",
    "bitnami/kafka-exporter",
    "bitnami/jmx-exporter",
    "prom/pushgateway",
    "bitnami/zookeeper",
    "bitnami/kafka",
}
KRAFT_IMAGE = "bitnamilegacy/kafka:3.9.0"


def render(name: str, chart: Path, values: list[Path], namespace: str) -> list[dict[str, Any]]:
    for item in [chart, *values]:
        if not item.exists():
            raise RuntimeError(f"Missing chart or values path: {item}")
    args = [
        "helm", "template", name, str(chart),
        "--namespace", namespace,
    ]
    for value in values:
        args.extend(["-f", str(value)])
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Helm render failed for {name}:\n{result.stderr}")
    return [
        document
        for document in yaml.safe_load_all(result.stdout)
        if isinstance(document, dict)
    ]


def image_records(documents: list[dict[str, Any]]) -> list[tuple[str, str, bool, str]]:
    records = []
    for document in documents:
        kind = document.get("kind", "")
        metadata = document.get("metadata") or {}
        name = metadata.get("name", "<unnamed>")
        annotations = metadata.get("annotations") or {}
        hook = str(annotations.get("helm.sh/hook", ""))
        # A Helm test hook is rendered by helm template but is not a startup dependency.
        test_only = bool(set(hook.replace(" ", "").split(",")) & {
            "test", "test-success", "test-failure",
        })
        spec = document.get("spec") or {}
        if kind in {"Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet", "ReplicationController"}:
            pod_spec = (spec.get("template") or {}).get("spec") or {}
        elif kind == "CronJob":
            pod_spec = (
                (((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}).get("spec")
                or {}
            )
        elif kind == "Pod":
            pod_spec = spec
        else:
            continue
        for category in ("initContainers", "containers", "ephemeralContainers"):
            for container in pod_spec.get(category) or []:
                image = str(container.get("image", "")).strip()
                if image:
                    records.append((f"{kind}/{name}", image, test_only, category))
    return records


def is_missing_image(image: str) -> bool:
    untagged = image.split("@", 1)[0].rsplit(":", 1)[0]
    return any(untagged == name or untagged.endswith("/" + name) for name in MISSING_IMAGES)


def main() -> int:
    print("===== SENTINEL OFFLINE IMAGE AUDIT (READ ONLY) =====")
    profiles = [
        (
            "sentinel-dev", "sentinel-dev", SENTINEL,
            [ROOT / "charts/sentinel/values-dev.yaml"],
        ),
        (
            "sentinel-prod", "sentinel-prod", SENTINEL,
            [ROOT / "charts/sentinel/values-prod.yaml"],
        ),
        (
            "clearml-serving-current", "sentinel-serving", SERVING,
            [SERVING_VALUES],
        ),
        (
            "clearml-serving-optional-kraft", "sentinel-kraft-test", SERVING,
            [SERVING_VALUES, KRAFT_VALUES],
        ),
    ]
    if (ROOT / "charts/sentinel/values-offline.yaml").exists():
        profiles.append((
            "sentinel-offline-override", "sentinel-dev", SENTINEL,
            [ROOT / "charts/sentinel/values-dev.yaml", ROOT / "charts/sentinel/values-offline.yaml"],
        ))

    errors = []
    for profile, namespace, chart, values in profiles:
        print(f"\n===== {profile} =====")
        try:
            records = image_records(render(profile, chart, values, namespace))
        except Exception as exc:
            errors.append(f"{profile}: {exc}")
            print(f"FAIL: {exc}")
            continue
        active = sorted({image for _, image, test_only, _ in records if not test_only})
        test_images = sorted({image for _, image, test_only, _ in records if test_only})
        print("Startup images:")
        for image in active:
            print(f"  {image}")
        if not active:
            print("  (none)")
        if test_images:
            print("Helm test-hook images (not started during normal install):")
            for image in test_images:
                print(f"  {image}")

        missing = [image for image in active if is_missing_image(image)]
        if missing:
            errors.append(f"{profile}: absent JFrog images required: {', '.join(missing)}")
            print("FAIL: One or more previously missing images are active")
        else:
            print("PASS: No previously missing Bitnami/Pushgateway images are startup dependencies")

        kafka = [image for image in active if image.endswith("/" + KRAFT_IMAGE) or image == KRAFT_IMAGE]
        if profile == "clearml-serving-optional-kraft":
            if kafka:
                print("PASS: Kafka 3.9.0 KRaft image present in optional profile")
            else:
                errors.append("Optional KRaft profile does not render the expected Kafka image")
                print("FAIL: Expected Kafka 3.9.0 image missing")
        if profile == "clearml-serving-current" and kafka:
            errors.append("Standard ClearML Serving profile unexpectedly enables Kafka")
            print("FAIL: Standard profile unexpectedly enables Kafka")

    if errors:
        print("\n===== ACTION REQUIRED =====")
        for error in errors:
            print(" -", error)
        return 1
    print("\nPASS: All checked profiles avoid the six missing images")
    print("NOTE: This checks Helm manifests, not JFrog availability or live Kubernetes runtime.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
