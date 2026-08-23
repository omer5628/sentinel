#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

POST_RENDERER_NAME="clearml-secret-postrenderer"
POST_RENDERER_DIR="${SCRIPT_DIR}/helm-plugins/${POST_RENDERER_NAME}"

if [[ -z "${SERVING_TASK_ID:-}" ]]; then
    echo "ERROR: SERVING_TASK_ID is required."
    echo "Example:"
    echo "  SERVING_TASK_ID=<task-id> ./scripts/deploy_clearml_serving.sh"
    exit 1
fi

if [[ ! -f "$HOME/clearml.conf" ]]; then
    echo "ERROR: $HOME/clearml.conf was not found."
    exit 1
fi

echo "Detecting Minikube host address..."

MINIKUBE_HOST_IP="$(
    minikube ssh -- \
        "getent hosts host.minikube.internal 2>/dev/null | awk 'NR==1 {print \$1}'" \
        | tr -d '\r'
)"

if [[ -z "$MINIKUBE_HOST_IP" ]]; then
    MINIKUBE_HOST_IP="$(
        minikube ssh -- \
            "ip route | awk '/^default/ {print \$3; exit}'" \
            | tr -d '\r'
    )"
fi

if [[ -z "$MINIKUBE_HOST_IP" ]]; then
    echo "ERROR: Could not determine Minikube host IP."
    exit 1
fi

API_HOST="${CLEARML_API_HOST_OVERRIDE:-http://${MINIKUBE_HOST_IP}:8008}"
WEB_HOST="${CLEARML_WEB_HOST_OVERRIDE:-http://${MINIKUBE_HOST_IP}:8080}"
FILES_HOST="${CLEARML_FILES_HOST_OVERRIDE:-http://${MINIKUBE_HOST_IP}:8081}"

echo "Minikube host: ${MINIKUBE_HOST_IP}"
echo "ClearML API: ${API_HOST}"
echo "ClearML Web: ${WEB_HOST}"
echo "ClearML Fileserver: ${FILES_HOST}"

TEMP_ENV_FILE="$(mktemp)"
chmod 600 "$TEMP_ENV_FILE"

cleanup() {
    rm -f "$TEMP_ENV_FILE"
}

trap cleanup EXIT

uv run --project "$REPO_ROOT" python - "$TEMP_ENV_FILE" <<'PY'
import re
import sys
from pathlib import Path

output_path = Path(sys.argv[1])
config_path = Path.home() / "clearml.conf"

text = config_path.read_text()

access = re.search(r'"access_key"\s*=\s*"([^"]+)"', text)
secret = re.search(r'"secret_key"\s*=\s*"([^"]+)"', text)

if not access or not secret:
    raise SystemExit("Could not read ClearML credentials from ~/clearml.conf")

output_path.write_text(
    f"CLEARML_API_ACCESS_KEY={access.group(1)}\n"
    f"CLEARML_API_SECRET_KEY={secret.group(1)}\n"
)
PY

echo "Updating Kubernetes credentials..."

kubectl create secret generic clearml-serving-credentials \
    --from-env-file="$TEMP_ENV_FILE" \
    --dry-run=client \
    -o yaml \
    | kubectl apply -f -

if ! helm plugin list | awk 'NR > 1 {print $1}' | \
    grep -qx "$POST_RENDERER_NAME"; then

    echo "Installing Helm post-renderer plugin..."

    helm plugin install "$POST_RENDERER_DIR"
fi

echo "Deploying ClearML Serving..."

helm upgrade --install clearml-serving clearml/clearml-serving \
    --namespace default \
    --version 1.6.2 \
    -f "$REPO_ROOT/serving/values-sentinel.yaml" \
    --set-string clearml.servingTaskId="$SERVING_TASK_ID" \
    --set-string clearml.apiHost="$API_HOST" \
    --set-string clearml.webHost="$WEB_HOST" \
    --set-string clearml.filesHost="$FILES_HOST" \
    --set-string clearml.apiAccessKey="MANAGED_BY_KUBERNETES_SECRET" \
    --set-string clearml.apiSecretKey="MANAGED_BY_KUBERNETES_SECRET" \
    --post-renderer "$POST_RENDERER_NAME"

echo "Waiting for ClearML Serving..."

kubectl rollout status deployment/clearml-serving-triton
kubectl rollout status deployment/clearml-serving-inference

echo
echo "ClearML Serving deployed successfully."
