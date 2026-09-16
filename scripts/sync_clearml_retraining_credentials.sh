#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

NAMESPACE="${CLEARML_RETRAINING_NAMESPACE:-sentinel-dev}"
SECRET_NAME="${CLEARML_RETRAINING_SECRET_NAME:-clearml-retraining-credentials}"
CONFIG_PATH="${CLEARML_CONFIG_PATH:-${HOME}/clearml.conf}"

if [[ ! -f "$CONFIG_PATH" ]]; then
    echo "ERROR: ClearML configuration was not found: $CONFIG_PATH"
    exit 1
fi

kubectl get namespace "$NAMESPACE" > /dev/null

TEMP_ENV_FILE="$(mktemp)"
chmod 600 "$TEMP_ENV_FILE"

cleanup() {
    rm -f "$TEMP_ENV_FILE"
}

trap cleanup EXIT

uv run --project "$REPO_ROOT" python - \
    "$CONFIG_PATH" \
    "$TEMP_ENV_FILE" <<'PY'
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])

text = config_path.read_text()

access_key = re.search(
    r'"access_key"\s*=\s*"([^"]+)"',
    text,
)

secret_key = re.search(
    r'"secret_key"\s*=\s*"([^"]+)"',
    text,
)

if access_key is None or secret_key is None:
    raise SystemExit(
        "Could not read ClearML credentials from the configuration file."
    )

output_path.write_text(
    "CLEARML_API_ACCESS_KEY="
    f"{access_key.group(1)}\n"
    "CLEARML_API_SECRET_KEY="
    f"{secret_key.group(1)}\n"
)
PY

if kubectl get secret \
    "$SECRET_NAME" \
    --namespace "$NAMESPACE" \
    > /dev/null 2>&1
then
    kubectl create secret generic \
        "$SECRET_NAME" \
        --namespace "$NAMESPACE" \
        --from-env-file="$TEMP_ENV_FILE" \
        --dry-run=client \
        -o yaml \
        | kubectl replace \
            --namespace "$NAMESPACE" \
            -f -
else
    kubectl create secret generic \
        "$SECRET_NAME" \
        --namespace "$NAMESPACE" \
        --from-env-file="$TEMP_ENV_FILE"
fi

echo "ClearML retraining credentials synchronized."
echo "Namespace: $NAMESPACE"
echo "Secret: $SECRET_NAME"
