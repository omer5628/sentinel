#!/usr/bin/env bash
# Disposable Kafka 3.9 KRaft integration test for the bundled Bitnami Kafka Helm chart.
# Never run this against an existing Kafka cluster or a production Kubernetes context.
set -Eeuo pipefail

cd "${SENTINEL_DIR:-$HOME/sentinel}"
CHART="external/helm-charts/clearml-serving/charts/kafka"
VALUES="serving/kafka-kraft-smoke-values.yaml"
IMAGE="bitnamilegacy/kafka:3.9.0"
RELEASE="sentinel-kraft-smoke"
CONTEXT="$(kubectl config current-context)"

for cmd in kubectl helm minikube docker python3; do
    command -v "$cmd" >/dev/null || { echo "FAIL: Required command not found: $cmd"; exit 1; }
done

# This guard deliberately refuses any non-Minikube Kubernetes context.
if [[ ! "$CONTEXT" =~ ^minikube($|-) ]]; then
    echo "STOP: Kubernetes context is '$CONTEXT', not Minikube. No resources changed."
    exit 1
fi

[[ -f "$VALUES" && -d "$CHART" ]] || {
    echo "FAIL: Kafka smoke values or chart not found. No resources changed."
    exit 1
}

kubectl cluster-info >/dev/null

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "===== PULL CANDIDATE KAFKA IMAGE ON THIS ONLINE MACHINE ====="
    docker pull "$IMAGE"
fi

echo "===== LOAD IMAGE INTO MINIKUBE ====="
minikube image load "$IMAGE"

NAMESPACE="sentinel-kraft-test-$(date +%s)-$RANDOM"
CLUSTER_ID="$(python3 - <<'PY'
import base64
import uuid
print(base64.urlsafe_b64encode(uuid.uuid4().bytes).rstrip(b'=').decode())
PY
)"
POD=""
CREATED=0

cleanup() {
    status=$?
    trap - EXIT
    if [[ "$CREATED" -eq 1 ]]; then
        if [[ "$status" -ne 0 ]]; then
            echo "===== FAILED: KUBERNETES DIAGNOSTICS ====="
            kubectl -n "$NAMESPACE" get pods,sts,svc -o wide || true
            kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 35 || true
            for p in $(kubectl -n "$NAMESPACE" get pods -o name 2>/dev/null); do
                echo "----- DESCRIBE $p -----"
                kubectl -n "$NAMESPACE" describe "$p" | tail -n 90 || true
                echo "----- LOGS $p -----"
                kubectl -n "$NAMESPACE" logs "$p" --all-containers --tail=120 || true
            done
        fi
        echo "===== REMOVING DISPOSABLE KAFKA RELEASE AND NAMESPACE ====="
        helm uninstall "$RELEASE" -n "$NAMESPACE" --wait --timeout 2m >/dev/null 2>&1 || true
        kubectl delete namespace "$NAMESPACE" --wait=false >/dev/null 2>&1 || true
        echo "Cleanup initiated for namespace: $NAMESPACE"
    fi
    exit "$status"
}
trap cleanup EXIT

echo "===== VERIFY HELM CHART ====="
helm lint "$CHART" -f "$VALUES"
echo "===== CREATE DISPOSABLE NAMESPACE ====="
kubectl create namespace "$NAMESPACE"
CREATED=1

echo "===== INSTALL KAFKA IN KRAFT MODE ====="
helm install "$RELEASE" "$CHART" \
    --namespace "$NAMESPACE" \
    -f "$VALUES" \
    --set-string "kraft.clusterId=$CLUSTER_ID" \
    --set "image.pullPolicy=IfNotPresent" \
    --timeout 5m

STS="$(kubectl -n "$NAMESPACE" get sts -l "app.kubernetes.io/instance=$RELEASE" -o jsonpath='{.items[0].metadata.name}')"
[[ -n "$STS" ]] || { echo "FAIL: No Kafka StatefulSet found"; exit 1; }
POD="$STS-0"

echo "===== WAIT FOR KAFKA STATEFULSET ====="
kubectl -n "$NAMESPACE" rollout status "statefulset/$STS" --timeout=300s

echo "===== VERIFY IMAGE AND KRAFT SETTINGS ====="
RUNNING_IMAGE="$(kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.spec.containers[0].image}')"
[[ "$RUNNING_IMAGE" == "$IMAGE" || "$RUNNING_IMAGE" == "docker.io/$IMAGE" ]] || {
    echo "FAIL: Unexpected Kafka image: $RUNNING_IMAGE"; exit 1;
}
kubectl -n "$NAMESPACE" exec "$POD" -- /bin/bash -ec '
    test "$KAFKA_ENABLE_KRAFT" = true
    case "$KAFKA_CFG_PROCESS_ROLES" in *broker*controller*|*controller*broker*) ;; *) exit 1 ;; esac
    echo "PASS: Kafka is configured for broker+controller KRaft"
'

if kubectl -n "$NAMESPACE" get pods -o name | grep -qi zookeeper; then
    echo "FAIL: ZooKeeper pod appeared in KRaft test"; exit 1
fi
echo "PASS: No ZooKeeper pod"

KAFKA_BIN="/opt/bitnami/kafka/bin"
TOPIC="sentinel-kraft-e2e"
MESSAGE="sentinel-kraft-roundtrip-$RANDOM-$RANDOM"

echo "===== VERIFY CONTROLLER QUORUM ====="
kubectl -n "$NAMESPACE" exec "$POD" -- "$KAFKA_BIN/kafka-metadata-quorum.sh" \
    --bootstrap-server localhost:9092 describe --status

echo "===== CREATE TOPIC ====="
kubectl -n "$NAMESPACE" exec "$POD" -- "$KAFKA_BIN/kafka-topics.sh" \
    --bootstrap-server localhost:9092 --create \
    --topic "$TOPIC" --partitions 1 --replication-factor 1

echo "===== PRODUCE MESSAGE ====="
printf '%s\n' "$MESSAGE" | kubectl -n "$NAMESPACE" exec -i "$POD" -- \
    "$KAFKA_BIN/kafka-console-producer.sh" \
    --bootstrap-server localhost:9092 --topic "$TOPIC"

echo "===== CONSUME MESSAGE ====="
RECEIVED="$(kubectl -n "$NAMESPACE" exec "$POD" -- \
    "$KAFKA_BIN/kafka-console-consumer.sh" \
    --bootstrap-server localhost:9092 --topic "$TOPIC" \
    --from-beginning --max-messages 1 --timeout-ms 30000)"
if [[ "$RECEIVED" != "$MESSAGE" ]]; then
    echo "FAIL: Unexpected consumer response: '$RECEIVED'"
    exit 1
fi

echo "PASS: Kafka 3.9.0 booted using Helm chart 21.4.0"
echo "PASS: KRaft quorum without ZooKeeper"
echo "PASS: Create topic, produce, consume round trip"
echo "SENTINEL KAFKA KRAFT K8S E2E: ALL CHECKS PASSED"
