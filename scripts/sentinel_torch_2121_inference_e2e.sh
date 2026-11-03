#!/usr/bin/env bash
# Offline-capable, disposable Sentinel inference-path E2E.
# Requires only local Docker images; does not touch Kubernetes, Compose,
# existing database volumes, host ports, or production services.
# The canary-compatible HTTP service runs a real TorchScript MNISTClassifier
# with synthetic/untrained weights. This does NOT validate ClearML Serving/Triton.
set -Eeuo pipefail

cd "${SENTINEL_ROOT:-$HOME/sentinel}"

WORKER_IMAGE='sentinel-worker:torch-2.12.1-test'
API_IMAGE='sentinel-api:torch-2.12.1-test'
RABBIT_IMAGE='rabbitmq:3-management'
REDIS_IMAGE='redis:7-alpine'
POSTGRES_IMAGE='postgres:16-alpine'

[[ -f infra/sql/init.sql ]] || { echo 'FAIL: infra/sql/init.sql missing'; exit 1; }
docker info >/dev/null
for image in "$WORKER_IMAGE" "$API_IMAGE" "$RABBIT_IMAGE" "$REDIS_IMAGE" "$POSTGRES_IMAGE"; do
  docker image inspect "$image" >/dev/null 2>&1 || { echo "FAIL: Missing local image: $image"; exit 1; }
done

echo '===== VERIFYING DOCKER IMAGE APPLICATION IMPORTS ====='
docker run --pull=never --rm --entrypoint python "$API_IMAGE" -c   'import sentinel.serving.api; print("PASS: Sentinel API import")'
docker run --pull=never --rm --entrypoint python "$WORKER_IMAGE" -c   'from sentinel.model import MNISTClassifier; print("PASS: Sentinel model import")'

NETWORK="sentinel-pred-e2e-$(date +%s)-${RANDOM}"
RABBIT="${NETWORK}-rabbitmq"
REDIS="${NETWORK}-redis"
POSTGRES="${NETWORK}-postgres"
WORKER="${NETWORK}-worker"
API="${NETWORK}-api"
CANARY="${NETWORK}-canary"
TEMP_DIR="$(mktemp -d /tmp/sentinel-pred-e2e-XXXXXX)"
NETWORK_CREATED=false

cleanup() {
  result=$?
  trap - EXIT
  if (( result != 0 )); then
    echo '===== E2E FAILED: CONTAINER DIAGNOSTICS ====='
    for name in "$API" "$CANARY" "$WORKER" "$RABBIT" "$POSTGRES"; do
      echo "--- $name ---"
      docker logs --tail 45 "$name" 2>&1 || true
    done
  fi
  for name in "$API" "$CANARY" "$WORKER" "$RABBIT" "$REDIS" "$POSTGRES"; do
    docker rm -f "$name" >/dev/null 2>&1 || true
  done
  if [[ "$NETWORK_CREATED" == true ]]; then
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$TEMP_DIR"
  if (( result == 0 )); then
    echo 'PASS: Disposable containers, network, and temporary script removed'
  fi
  exit "$result"
}
trap cleanup EXIT

wait_exec() {
  local container=$1
  shift
  for _ in $(seq 1 90); do
    if [[ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" != true ]]; then
      echo "FAIL: $container stopped during startup"
      return 1
    fi
    if docker exec "$container" "$@" >/dev/null 2>&1; then
      echo "READY: $container"
      return 0
    fi
    sleep 2
  done
  echo "FAIL: $container not ready"
  return 1
}

cat > "$TEMP_DIR/canary_torchscript.py" <<'PY'
"""Disposable canary-shaped HTTP endpoint running a real TorchScript model.

This tests Sentinel's HTTP contract and PyTorch 2.12.1 computations.
Weights are synthetic/untrained; ClearML Serving and Triton are not used.
"""
import json
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import torch

from sentinel.model import MNISTClassifier

torch.set_num_threads(1)
model = MNISTClassifier().eval().cpu()
with tempfile.TemporaryDirectory() as dirname:
    path = Path(dirname) / 'e2e_model.pt'
    torch.jit.save(torch.jit.script(model), str(path))
    loaded_model = torch.jit.load(str(path), map_location='cpu').eval()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print('HTTP:', fmt % args, flush=True)

    def respond(self, status, payload):
        body = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/healthz':
            self.respond(200, {'status': 'ready', 'torch': torch.__version__})
        else:
            self.respond(404, {'detail': 'not found'})

    def do_POST(self):
        if self.path != '/serve/sentinel-mnist-canary':
            self.respond(404, {'detail': 'not found'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length <= 0 or length > 200000:
                raise ValueError('Invalid payload length')
            body = json.loads(self.rfile.read(length))
            tensor = torch.tensor(body['pixels'], dtype=torch.float32)
            if tensor.shape != (1, 1, 28, 28):
                raise ValueError(f'Invalid tensor shape: {tensor.shape}')
            with torch.inference_mode():
                probabilities = torch.softmax(loaded_model(tensor), dim=1)
                confidence, predicted_class = probabilities.max(dim=1)
            self.respond(200, {
                'predicted_class': int(predicted_class.item()),
                'confidence': float(confidence.item()),
                'model_version': 'e2e-torch-2.12.1',
            })
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self.respond(400, {'detail': str(error)})

print('TorchScript inference backend ready; torch=', torch.__version__, flush=True)
ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
PY
chmod 644 "$TEMP_DIR/canary_torchscript.py"

echo '===== CREATE PRIVATE E2E NETWORK (NO INTERNET EGRESS) ====='
docker network create --internal "$NETWORK" >/dev/null
NETWORK_CREATED=true

echo '===== START DISPOSABLE INFRASTRUCTURE ====='
docker run --pull=never -d --name "$RABBIT" --network "$NETWORK" \
  --network-alias rabbitmq \
  -e RABBITMQ_DEFAULT_USER=sentinel -e RABBITMQ_DEFAULT_PASS=sentinel \
  "$RABBIT_IMAGE" >/dev/null

docker run --pull=never -d --name "$REDIS" --network "$NETWORK" \
  --network-alias redis "$REDIS_IMAGE" >/dev/null

docker run --pull=never -d --name "$POSTGRES" --network "$NETWORK" \
  --network-alias postgres \
  -e POSTGRES_DB=sentinel -e POSTGRES_USER=sentinel -e POSTGRES_PASSWORD=sentinel \
  --mount "type=bind,src=$PWD/infra/sql/init.sql,dst=/docker-entrypoint-initdb.d/init.sql,readonly" \
  "$POSTGRES_IMAGE" >/dev/null

# Always run rabbitmq-diagnostics as the rabbitmq user; running it as root
# can create /var/lib/rabbitmq/.erlang.cookie with the wrong ownership.
wait_exec "$RABBIT" sh -c 'true'
for _ in $(seq 1 90); do
  if docker exec --user rabbitmq "$RABBIT" rabbitmq-diagnostics -q ping >/dev/null 2>&1; then
    echo 'READY: RabbitMQ'
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$RABBIT")" != true ]]; then
    echo 'FAIL: RabbitMQ exited'
    exit 1
  fi
  sleep 2
done
docker exec --user rabbitmq "$RABBIT" rabbitmq-diagnostics -q ping >/dev/null
wait_exec "$REDIS" redis-cli ping
wait_exec "$POSTGRES" pg_isready -U sentinel -d sentinel

SCHEMA_READY=false
for _ in $(seq 1 90); do
  value="$(docker exec "$POSTGRES" psql -U sentinel -d sentinel -tAc \
    "SELECT 1 FROM schema_registry WHERE schema_name='image_message' AND schema_version='v1' AND is_active=TRUE" 2>/dev/null || true)"
  if [[ "$value" == '1' ]]; then SCHEMA_READY=true; break; fi
  sleep 2
done
[[ "$SCHEMA_READY" == true ]] || { echo 'FAIL: DB schema initialization timeout'; exit 1; }
echo 'PASS: PostgreSQL schema registry initialized'

echo '===== START WORKER WITH TORCH 2.12.1 ====='
docker run --pull=never -d --name "$WORKER" --network "$NETWORK" \
  -e RABBITMQ_HOST=rabbitmq -e RABBITMQ_USERNAME=sentinel -e RABBITMQ_PASSWORD=sentinel \
  -e REDIS_HOST=redis -e POSTGRES_HOST=postgres \
  -e POSTGRES_DB=sentinel -e POSTGRES_USER=sentinel -e POSTGRES_PASSWORD=sentinel \
  -e WORKER_FEATURE_TTL_SECONDS=240 -e AUTO_INFERENCE_ENABLED=false \
  "$WORKER_IMAGE" >/dev/null
WORKER_READY=false
for _ in $(seq 1 90); do
  if docker logs "$WORKER" 2>&1 | grep -q 'Waiting for messages from queue'; then
    WORKER_READY=true
    break
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$WORKER")" != true ]]; then
    echo 'FAIL: Worker exited'
    exit 1
  fi
  sleep 2
done
[[ "$WORKER_READY" == true ]] || { echo 'FAIL: Worker not ready'; exit 1; }
echo 'PASS: Worker ready'

echo '===== START TORCHSCRIPT BACKEND (CANARY HTTP CONTRACT) ====='
docker run --pull=never -d --name "$CANARY" --network "$NETWORK" \
  --network-alias canary \
  --mount "type=bind,src=$TEMP_DIR/canary_torchscript.py,dst=/tmp/canary_torchscript.py,readonly" \
  --entrypoint python "$WORKER_IMAGE" -u /tmp/canary_torchscript.py >/dev/null
wait_exec "$CANARY" python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=2).status == 200"

echo '===== START SENTINEL SERVING API ====='
docker run --pull=never -d --name "$API" --network "$NETWORK" \
  --network-alias sentinel-api \
  -e REDIS_HOST=redis -e REDIS_PORT=6379 \
  -e RABBITMQ_HOST=rabbitmq -e RABBITMQ_USERNAME=sentinel -e RABBITMQ_PASSWORD=sentinel \
  -e CLEARML_CANARY_URL=http://canary:8080/serve/sentinel-mnist-canary \
  -e OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces \
  "$API_IMAGE" >/dev/null
wait_exec "$API" python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=2).status == 200"

echo '===== PRODUCER -> WORKER -> REDIS -> API -> TORCHSCRIPT -> INFERENCE EVENT ====='
docker run --pull=never --rm -i --network "$NETWORK" \
  --entrypoint python "$WORKER_IMAGE" - <<'PY'
import base64
import time
from io import BytesIO
from uuid import uuid4

import httpx
import pika
import psycopg2
import redis
import torch
from PIL import Image

from sentinel.schema.v1 import ImageMessageV1

assert torch.__version__.split('+')[0] == '2.12.1'
print('PASS: Client PyTorch', torch.__version__, flush=True)

connection = pika.BlockingConnection(pika.ConnectionParameters(
    host='rabbitmq', credentials=pika.PlainCredentials('sentinel', 'sentinel')
))
channel = connection.channel()
channel.queue_declare(queue='video_stream', passive=True)
feature_store = redis.Redis(host='redis')
postgres = psycopg2.connect(
    host='postgres', dbname='sentinel', user='sentinel', password='sentinel'
)
client = httpx.Client(base_url='http://sentinel-api:8000', timeout=30.0)

missing = client.post('/predict/e2e-nonexistent-image')
assert missing.status_code == 404, (missing.status_code, missing.text)
print('PASS: Missing image returns 404', flush=True)

image_id = f'e2e-inference-{uuid4().hex[:12]}'
event_id = uuid4()
inference_id = uuid4()
image = Image.new('L', (28, 28), color=128)
buffer = BytesIO()
image.save(buffer, format='PNG')
raw = buffer.getvalue()
message = ImageMessageV1(
    schema_version='v1',
    event_id=event_id,
    image_id=image_id,
    timestamp=time.time(),
    image_format='png',
    image_base64=base64.b64encode(raw).decode('ascii'),
)
channel.basic_publish(
    exchange='', routing_key='video_stream',
    body=message.model_dump_json().encode(),
    properties=pika.BasicProperties(delivery_mode=2, content_type='application/json'),
)
print('SENT: PNG image', image_id, flush=True)

feature = None
stored_row = None
for _ in range(120):
    feature = feature_store.get(f'feat:{image_id}')
    with postgres.cursor() as cursor:
        cursor.execute('SELECT raw_image FROM feature_log WHERE event_id=%s', (str(event_id),))
        stored_row = cursor.fetchone()
    if feature is not None and stored_row is not None:
        break
    time.sleep(1)
assert feature is not None, 'Redis feature missing'
assert len(feature) == 28 * 28 * 4, f'Unexpected Redis feature size: {len(feature)}'
assert stored_row is not None and bytes(stored_row[0]) == raw, 'PostgreSQL raw image mismatch'
print('PASS: Worker persisted image in Redis and PostgreSQL', flush=True)

response = client.post(
    f'/predict/{image_id}',
    headers={'X-Inference-Request-ID': str(inference_id)},
)
assert response.status_code == 200, (response.status_code, response.text)
result = response.json()
assert result['image_id'] == image_id
assert result['model_version'] == 'e2e-torch-2.12.1'
assert result['predicted_label'] == str(result['predicted_class'])
assert 0 <= result['predicted_class'] <= 9
assert 0.0 <= result['confidence'] <= 1.0
print('PASS: API performed real TorchScript inference:', result, flush=True)

inference_event = None
for _ in range(30):
    try:
        channel.queue_declare(queue='inference_events', passive=True)
    except pika.exceptions.ChannelClosedByBroker:
        channel = connection.channel()
        time.sleep(1)
        continue
    method, properties, body = channel.basic_get(queue='inference_events', auto_ack=False)
    if method is not None:
        import json
        inference_event = json.loads(body)
        channel.basic_ack(method.delivery_tag)
        break
    time.sleep(1)
assert inference_event is not None, 'No inference event published'
assert inference_event['image_id'] == image_id
assert inference_event['inference_id'] == str(inference_id)
assert inference_event['model_version'] == result['model_version']
assert inference_event['predicted_class'] == result['predicted_class']
print('PASS: Inference event published to RabbitMQ', flush=True)

metrics_response = client.get('/metrics')
assert metrics_response.status_code == 200
assert 'model_predictions_total{' in metrics_response.text, 'Prometheus prediction metric absent'
print('PASS: Prometheus prediction counter populated', flush=True)

client.close()
postgres.close()
feature_store.close()
connection.close()
print('SENTINEL PYTORCH 2.12.1 INFERENCE E2E: ALL CHECKS PASSED', flush=True)
PY

echo '===== PASS: INFERENCE PATH E2E ====='
