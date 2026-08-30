#!/usr/bin/env bash

set -Eeuo pipefail

BACKUP_ROOT="${SENTINEL_PERSISTENT_DIR:-$HOME/sentinel-persistent}"
BACKUP_DIR="${BACKUP_ROOT}/jenkins"

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
