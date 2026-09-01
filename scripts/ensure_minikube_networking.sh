#!/bin/bash

set -euo pipefail

echo "Checking Minikube service networking..."

if ! kubectl get configmap kube-proxy \
    -n kube-system \
    >/dev/null 2>&1; then
    echo "ERROR: kube-proxy ConfigMap is not available."
    exit 1
fi

CURRENT_CONFIG="$(
    kubectl get configmap kube-proxy \
        -n kube-system \
        -o jsonpath='{.data.config\.conf}'
)"

if printf '%s\n' "${CURRENT_CONFIG}" \
    | sed -n '/^iptables:/,/^[^[:space:]]/p' \
    | grep -Eq '^[[:space:]]+masqueradeAll:[[:space:]]+true$'; then
    echo "Minikube service networking verified: masqueradeAll=true"
    exit 0
fi

if ! printf '%s\n' "${CURRENT_CONFIG}" \
    | sed -n '/^iptables:/,/^[^[:space:]]/p' \
    | grep -Eq '^[[:space:]]+masqueradeAll:[[:space:]]+false$'; then
    echo "ERROR: Could not determine iptables.masqueradeAll configuration."
    exit 1
fi

echo "Updating kube-proxy: masqueradeAll=true..."

TMP_FILE="$(mktemp)"
trap 'rm -f "${TMP_FILE}"' EXIT

kubectl get configmap kube-proxy \
    -n kube-system \
    -o json \
    > "${TMP_FILE}"

python3 - "${TMP_FILE}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
obj = json.loads(path.read_text())

config = obj["data"]["config.conf"]
lines = config.splitlines()

inside_iptables = False
changed = False

for index, line in enumerate(lines):
    if line == "iptables:":
        inside_iptables = True
        continue

    if inside_iptables and line and not line[0].isspace():
        break

    if inside_iptables and line.strip().startswith("masqueradeAll:"):
        current_value = line.split(":", 1)[1].strip()

        if current_value not in {"true", "false"}:
            raise SystemExit(
                f"Unexpected masqueradeAll value: {current_value}"
            )

        indentation = line[: len(line) - len(line.lstrip())]
        lines[index] = f"{indentation}masqueradeAll: true"
        changed = current_value != "true"
        break

if not changed:
    raise SystemExit(
        "Could not update iptables.masqueradeAll from false to true"
    )

obj["data"]["config.conf"] = "\n".join(lines) + "\n"

path.write_text(json.dumps(obj))
PY

kubectl replace \
    -f "${TMP_FILE}" \
    >/dev/null

echo "Restarting kube-proxy..."

kubectl rollout restart daemonset kube-proxy \
    -n kube-system \
    >/dev/null

kubectl rollout status daemonset kube-proxy \
    -n kube-system \
    --timeout=120s

UPDATED_CONFIG="$(
    kubectl get configmap kube-proxy \
        -n kube-system \
        -o jsonpath='{.data.config\.conf}'
)"

if ! printf '%s\n' "${UPDATED_CONFIG}" \
    | sed -n '/^iptables:/,/^[^[:space:]]/p' \
    | grep -Eq '^[[:space:]]+masqueradeAll:[[:space:]]+true$'; then
    echo "ERROR: Minikube service networking verification failed."
    exit 1
fi

echo "Minikube service networking restored: masqueradeAll=true"
