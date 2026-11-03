#!/usr/bin/env bash
# Diagnostic-only Trivy scan: downloads vulnerability DB while online,
# then scans the local Sentinel image with network access disabled.
# Findings are NOT suppressed or treated as a passing security gate.
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-$HOME/sentinel}"
TARGET_IMAGE="${TARGET_IMAGE:-sentinel-validator:pinned-images-test}"
TRIVY_IMAGE="aquasec/trivy:0.74.0"
CACHE_DIR="$HOME/.cache/sentinel-trivy-0.74.0"
REPORT_DIR="$HOME/sentinel-trivy-reports"

cd "$PROJECT_DIR"
docker info >/dev/null
docker image inspect "$TARGET_IMAGE" >/dev/null
docker image inspect "$TRIVY_IMAGE" >/dev/null
mkdir -p "$CACHE_DIR" "$REPORT_DIR"
WORK_DIR="$(mktemp -d "$HOME/sentinel-trivy-diagnose-XXXXXXXX")"
trap 'rm -rf "$WORK_DIR"' EXIT

if [[ -f .trivyignore.yaml ]]; then
  cp .trivyignore.yaml "$WORK_DIR/ignore.yaml"
else
  printf 'vulnerabilities: []\n' > "$WORK_DIR/ignore.yaml"
fi

echo '===== PREPARING LOCAL VULNERABILITY DATABASE ====='
if [[ ! -s "$CACHE_DIR/db/trivy.db" || ! -s "$CACHE_DIR/db/metadata.json" ]]; then
  docker run --rm --pull=never \
    --user "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$CACHE_DIR:/cache" \
    "$TRIVY_IMAGE" image --cache-dir /cache --download-db-only
else
  echo 'PASS: Reusing cached Trivy database'
fi

echo '===== EXPORTING LOCAL IMAGE ====='
docker save --output "$WORK_DIR/image.tar" "$TARGET_IMAGE"
cp "$WORK_DIR/ignore.yaml" "$WORK_DIR/ignore-for-container.yaml"

REPORT="$REPORT_DIR/validator-critical-$(date +%Y%m%d-%H%M%S).json"
echo '===== SCANNING WITH NETWORK DISABLED ====='
docker run --rm --pull=never --network none \
  --user "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$CACHE_DIR:/cache" -v "$WORK_DIR:/work" \
  -v "$REPORT_DIR:/reports" \
  "$TRIVY_IMAGE" image \
  --cache-dir /cache --input /work/image.tar \
  --scanners vuln --severity CRITICAL \
  --ignorefile /work/ignore-for-container.yaml \
  --skip-db-update --skip-java-db-update --skip-check-update \
  --offline-scan --skip-version-check --format json \
  --output "/reports/$(basename "$REPORT")" --exit-code 0

echo '===== CRITICAL FINDINGS BY PACKAGE ====='
python3 - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
report = json.loads(path.read_text())
results = report.get("Results")
if not isinstance(results, list):
    raise SystemExit("FAIL: No valid Results list in Trivy JSON report")
findings = []
for result in results:
    for item in result.get("Vulnerabilities") or []:
        if item.get("Severity") != "CRITICAL":
            continue
        findings.append((
            result.get("Type") or "unknown",
            item.get("PkgName") or "unknown",
            item.get("InstalledVersion") or "unknown",
            item.get("FixedVersion") or "NOT LISTED",
            item.get("VulnerabilityID") or "unknown",
        ))
print(f"Total CRITICAL findings: {len(findings)}")
print(f"Unique package/CVE entries: {len(set(findings))}")
for kind, pkg, installed, fixed, cve in sorted(set(findings)):
    print(f"{kind} | {pkg} | installed={installed} | fixed={fixed} | {cve}")
print(f"\nFull JSON report: {path}")
if findings:
    print("SECURITY GATE REMAINS BLOCKED until vulnerabilities are remediated or reviewed")
else:
    print("NO CRITICAL FINDINGS in this diagnostic scan")
PY

echo '===== DIAGNOSTIC COMPLETE; NO JENKINS SECURITY POLICY CHANGED ====='
