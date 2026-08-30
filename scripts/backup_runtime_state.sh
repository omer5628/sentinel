#!/usr/bin/env bash

set -Eeuo pipefail

BACKUP_ROOT="${SENTINEL_PERSISTENT_DIR:-$HOME/sentinel-persistent}"
BACKUP_DIR="${BACKUP_ROOT}/jenkins"
SECRETS_BACKUP_DIR="${BACKUP_ROOT}/secrets"

JENKINS_NAMESPACE="jenkins"
JENKINS_STATEFULSET="jenkins"
JENKINS_PVC="jenkins"
BACKUP_POD="jenkins-backup"

ARCHIVE="${BACKUP_DIR}/jenkins-home.tar.gz"
CHECKSUM="${ARCHIVE}.sha256"

ORIGINAL_REPLICAS=""
BACKUP_POD_CREATED=false
TEMP_ARCHIVE=""


cleanup() {
    exit_code=$?

    set +e

    if [[ -n "$TEMP_ARCHIVE" && -f "$TEMP_ARCHIVE" ]]; then
        rm -f "$TEMP_ARCHIVE"
    fi

    if [[ "$BACKUP_POD_CREATED" == "true" ]]; then
        echo "Removing temporary Jenkins backup pod..."

        kubectl delete pod "$BACKUP_POD" \
            -n "$JENKINS_NAMESPACE" \
            --ignore-not-found \
            --wait=true >/dev/null
    fi

    if [[ -n "$ORIGINAL_REPLICAS" && "$ORIGINAL_REPLICAS" -gt 0 ]]; then
        echo "Restoring Jenkins replicas to ${ORIGINAL_REPLICAS}..."

        kubectl scale statefulset "$JENKINS_STATEFULSET" \
            -n "$JENKINS_NAMESPACE" \
            --replicas="$ORIGINAL_REPLICAS" >/dev/null

        kubectl rollout status \
            statefulset/"$JENKINS_STATEFULSET" \
            -n "$JENKINS_NAMESPACE" \
            --timeout=5m
    fi

    exit "$exit_code"
}


trap cleanup EXIT


backup_secrets() {
    echo "Backing up Kubernetes secrets..."

    mkdir -p "$SECRETS_BACKUP_DIR"
    chmod 700 "$SECRETS_BACKUP_DIR"

    uv run python - "$SECRETS_BACKUP_DIR" <<'PYTHON'
import json
import subprocess
import sys
from pathlib import Path

import yaml

backup_dir = Path(sys.argv[1])

secrets = [
    ("default", "clearml-serving-credentials"),
    ("default", "sentinel-service-secrets"),
    ("sentinel-dev", "grafana-admin-credentials"),
    ("sentinel-dev", "sentinel-service-secrets"),
]

for namespace, name in secrets:
    raw = subprocess.check_output(
        [
            "kubectl",
            "get",
            "secret",
            name,
            "-n",
            namespace,
            "-o",
            "json",
        ],
        text=True,
    )

    source = json.loads(raw)

    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": name,
            "namespace": namespace,
        },
        "type": source["type"],
        "data": source["data"],
    }

    output = backup_dir / f"{namespace}-{name}.yaml"

    output.write_text(
        yaml.safe_dump(
            manifest,
            sort_keys=False,
        )
    )

    output.chmod(0o600)
PYTHON

    (
        cd "$SECRETS_BACKUP_DIR"

        sha256sum \
            default-clearml-serving-credentials.yaml \
            default-sentinel-service-secrets.yaml \
            sentinel-dev-grafana-admin-credentials.yaml \
            sentinel-dev-sentinel-service-secrets.yaml \
            > SHA256SUMS

        chmod 600 SHA256SUMS

        sha256sum -c SHA256SUMS
    )

    echo "Kubernetes secrets backup completed successfully."
}


echo "Checking Jenkins resources..."

kubectl get namespace "$JENKINS_NAMESPACE" >/dev/null

kubectl get statefulset "$JENKINS_STATEFULSET" \
    -n "$JENKINS_NAMESPACE" >/dev/null

kubectl get pvc "$JENKINS_PVC" \
    -n "$JENKINS_NAMESPACE" >/dev/null


ORIGINAL_REPLICAS="$(
    kubectl get statefulset "$JENKINS_STATEFULSET" \
        -n "$JENKINS_NAMESPACE" \
        -o jsonpath='{.spec.replicas}'
)"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_ROOT" "$BACKUP_DIR"


backup_secrets


echo "Stopping Jenkins..."

kubectl scale statefulset "$JENKINS_STATEFULSET" \
    -n "$JENKINS_NAMESPACE" \
    --replicas=0 >/dev/null

if kubectl get pod jenkins-0 \
    -n "$JENKINS_NAMESPACE" >/dev/null 2>&1; then

    kubectl wait \
        --for=delete \
        pod/jenkins-0 \
        -n "$JENKINS_NAMESPACE" \
        --timeout=120s
fi


echo "Creating temporary backup pod..."

kubectl delete pod "$BACKUP_POD" \
    -n "$JENKINS_NAMESPACE" \
    --ignore-not-found \
    --wait=true >/dev/null

kubectl apply -f - <<YAML >/dev/null
apiVersion: v1
kind: Pod
metadata:
  name: ${BACKUP_POD}
  namespace: ${JENKINS_NAMESPACE}
spec:
  restartPolicy: Never
  containers:
    - name: backup
      image: alpine:3.22
      command:
        - sh
        - -c
        - sleep 36000
      volumeMounts:
        - name: jenkins-home
          mountPath: /var/jenkins_home
  volumes:
    - name: jenkins-home
      persistentVolumeClaim:
        claimName: ${JENKINS_PVC}
YAML

BACKUP_POD_CREATED=true

kubectl wait \
    --for=condition=Ready \
    pod/"$BACKUP_POD" \
    -n "$JENKINS_NAMESPACE" \
    --timeout=120s


echo "Creating Jenkins backup..."

TEMP_ARCHIVE="$(
    mktemp "${BACKUP_DIR}/.jenkins-home.XXXXXX.tar.gz"
)"

kubectl exec \
    -n "$JENKINS_NAMESPACE" \
    "$BACKUP_POD" \
    -- tar -czf - -C /var/jenkins_home . \
    > "$TEMP_ARCHIVE"


echo "Validating archive..."

tar -tzf "$TEMP_ARCHIVE" >/dev/null


if [[ -f "$ARCHIVE" ]]; then
    mv -f "$ARCHIVE" "${ARCHIVE}.previous"

    if [[ -f "$CHECKSUM" ]]; then
        mv -f "$CHECKSUM" "${CHECKSUM}.previous"
    fi
fi


mv "$TEMP_ARCHIVE" "$ARCHIVE"
TEMP_ARCHIVE=""

(
    cd "$BACKUP_DIR"
    sha256sum jenkins-home.tar.gz > jenkins-home.tar.gz.sha256
    sha256sum -c jenkins-home.tar.gz.sha256
)

chmod 600 \
    "$ARCHIVE" \
    "$CHECKSUM"

if [[ -f "${ARCHIVE}.previous" ]]; then
    chmod 600 "${ARCHIVE}.previous"
fi

if [[ -f "${CHECKSUM}.previous" ]]; then
    chmod 600 "${CHECKSUM}.previous"
fi


echo
echo "Jenkins backup completed successfully."
echo "Backup: ${ARCHIVE}"
