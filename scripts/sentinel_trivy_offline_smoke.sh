#!/usr/bin/env bash
# Smoke-test Trivy's vulnerability scanner without network access during scanning.
# This script does not modify Jenkins, Kubernetes, or the project dependency locks.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/sentinel}"
TRIVY_IMAGE="aquasec/trivy:0.74.0"
TARGET_IMAGE="${TARGET_IMAGE:-sentinel-validator:pinned-images-test}"

cd "$PROJECT_DIR"
command -v docker >/dev/null
command -v python3 >/dev/null
docker info >/dev/null

docker image inspect "$TRIVY_IMAGE" >/dev/null || {
  echo "FAIL: Trivy image not available locally: $TRIVY_IMAGE" >&2
  exit 1
}
docker image inspect "$TARGET_IMAGE" >/dev/null || {
  echo "FAIL: Target image not available locally: $TARGET_IMAGE" >&2
  exit 1
}

WORK_DIR="$(mktemp -d "$HOME/sentinel-trivy-smoke-XXXXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT
mkdir -p "$WORK_DIR/cache" "$WORK_DIR/output"

if [[ -f .trivyignore.yaml ]]; then
  cp .trivyignore.yaml "$WORK_DIR/output/ignore.yaml"
else
  echo 'vulnerabilities: []' > "$WORK_DIR/output/ignore.yaml"
fi

echo '===== 1. PREPARE TRIVY VULNERABILITY DATABASE (ONLINE MACHINE ONLY) ====='
docker run --rm --pull=never \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  -v "$WORK_DIR/cache:/cache" \
  "$TRIVY_IMAGE" image \
  --cache-dir /cache \
  --download-db-only

test -s "$WORK_DIR/cache/db/trivy.db"
test -s "$WORK_DIR/cache/db/metadata.json"
echo 'PASS: Trivy vulnerability DB downloaded and validated'

echo '===== 2. EXPORT A LOCAL SENTINEL IMAGE ====='
docker save --output "$WORK_DIR/output/image.tar" "$TARGET_IMAGE"
test -s "$WORK_DIR/output/image.tar"
echo "PASS: Docker archive created for $TARGET_IMAGE"

echo '===== 3. SCAN WITH DOCKER NETWORK DISABLED ====='
docker run --rm --pull=never \
  --network none \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  -v "$WORK_DIR/cache:/cache" \
  -v "$WORK_DIR/output:/work" \
  "$TRIVY_IMAGE" image \
  --cache-dir /cache \
  --input /work/image.tar \
  --scanners vuln \
  --severity CRITICAL \
  --ignorefile /work/ignore.yaml \
  --skip-db-update \
  --skip-java-db-update \
  --skip-check-update \
  --offline-scan \
  --skip-version-check \
  --format json \
  --output /work/report.json \
  --exit-code 0

echo '===== 4. CHECK REPORT AND ENFORCE THE SAME CRITICAL SEVERITY GATE ====='
python3 - "$WORK_DIR/output/report.json" "$TARGET_IMAGE" <<'PY'
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text())
if not isinstance(report.get("Results"), list):
    raise SystemExit("FAIL: Trivy did not return a valid scan result")

critical = [
    (result.get("Target", "unknown"), item.get("VulnerabilityID", "unknown"))
    for result in report["Results"]
    for item in (result.get("Vulnerabilities") or [])
    if item.get("Severity") == "CRITICAL"
]
print("PASS: Real Trivy image scan completed with --network none")
print(f"Target image: {sys.argv[2]}")
print(f"Critical findings after ignore policy: {len(critical)}")
for target, cve in critical[:10]:
    print(f"  {target}: {cve}")
if critical:
    raise SystemExit("SECURITY GATE BLOCKED: CRITICAL vulnerabilities found (scanner works)")
print("PASS: CRITICAL vulnerability gate")
PY

echo '===== TRIVY OFFLINE SMOKE: ALL CHECKS PASSED ====='
