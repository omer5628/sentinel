#!/usr/bin/env bash
# Isolated Sentinel ingestion E2E for the built PyTorch 2.12.1 Worker image.
# Creates disposable Docker containers and a private network; no host ports,
# existing Compose services, database volumes, or Kubernetes deployments touched.
set -Eeuo pipefail

cd "${SENTINEL_ROOT:-$HOME/sentinel}"

WORKER_IMAGE='sentinel-worker:torch-2.12.1-test'
RABBIT_IMAGE='rabbitmq:3-management'
REDIS_IMAGE='redis:7-alpine'
POSTGRES_IMAGE='postgres:16-alpine'

[[ -f infra/sql/init.sql ]] || { echo 'FAIL: infra/sql/init.sql not found'; exit 1; }
docker info >/dev/null
for image in "$WORKER_IMAGE" "$RABBIT_IMAGE" "$REDIS_IMAGE" "$POSTGRES_IMAGE"; do
  docker image inspect "$image" >/dev/null 2>&1 || {
    echo "FAIL: Missing local image: $image";
    echo 'For missing infrastructure images, pull them on the connected machine before rerunning.'
    exit 1
  }
done

NETWORK="sentinel-e2e-$(date +%s)-${RANDOM}"
RABBIT="${NETWORK}-rabbitmq"
REDIS="${NETWORK}-redis"
POSTGRES="${NETWORK}-postgres"
WORKER="${NETWORK}-worker"
NETWORK_CREATED=false

cleanup() {
  status=$?
  trap - EXIT
  if (( status != 0 )); then
    echo '===== E2E FAILED: DIAGNOSTIC LOGS ====='
    # The worker may not have been started if infrastructure initialization failed.
    if docker container inspect "$WORKER" >/dev/null 2>&1; then
      docker logs --tail 100 "$WORKER" 2>&1 || true
    fi
    docker logs --tail 35 "$POSTGRES" 2>&1 || true
    docker logs --tail 50 "$RABBIT" 2>&1 || true
  fi
  for name in "$WORKER" "$RABBIT" "$REDIS" "$POSTGRES"; do
    # -v removes only anonymous volumes belonging to these disposable containers.
    docker rm -fv "$name" >/dev/null 2>&1 || true
  done
  if [[ "$NETWORK_CREATED" == true ]]; then
    docker network rm "$NETWORK" >/dev/null 2>&1 || true
  fi
  if (( status == 0 )); then
    echo 'PASS: Disposable Docker resources removed; existing services untouched.'
  fi
  exit "$status"
}
trap cleanup EXIT

wait_for() {
  local name=$1
  shift
  # RabbitMQ runs as the 'rabbitmq' user; using default root for an early
  # rabbitmq-diagnostics call can create a root-owned .erlang.cookie before
  # the broker creates it, causing RabbitMQ to crash with EACCES.
  # Use the broker user for *every* CLI check, even during startup.
  local -a exec_opts=()
  if [[ "$name" == "$RABBIT" ]]; then
    exec_opts=(--user rabbitmq)
  fi
  for _ in $(seq 1 90); do
    if docker exec "${exec_opts[@]}" "$name" "$@" >/dev/null 2>&1; then
      echo "READY: $name"
      return 0
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || true)" == 'false' ]]; then
      echo "FAIL: $name exited during startup"
      return 1
    fi
    sleep 2
  done
  echo "FAIL: $name did not become ready"
  return 1
}

echo '===== CREATING ISOLATED E2E NETWORK ====='
docker network create "$NETWORK" >/dev/null
NETWORK_CREATED=true

echo '===== STARTING DISPOSABLE INFRASTRUCTURE ====='
docker run --pull=never -d --name "$RABBIT" \
  --network "$NETWORK" --network-alias rabbitmq \
  -e RABBITMQ_DEFAULT_USER=sentinel \
  -e RABBITMQ_DEFAULT_PASS=sentinel \
  "$RABBIT_IMAGE" >/dev/null

docker run --pull=never -d --name "$REDIS" \
  --network "$NETWORK" --network-alias redis \
  "$REDIS_IMAGE" >/dev/null

docker run --pull=never -d --name "$POSTGRES" \
  --network "$NETWORK" --network-alias postgres \
  -e POSTGRES_DB=sentinel \
  -e POSTGRES_USER=sentinel \
  -e POSTGRES_PASSWORD=sentinel \
  --mount "type=bind,src=$PWD/infra/sql/init.sql,dst=/docker-entrypoint-initdb.d/init.sql,readonly" \
  "$POSTGRES_IMAGE" >/dev/null

wait_for "$RABBIT" rabbitmq-diagnostics -q ping
wait_for "$REDIS" redis-cli ping
wait_for "$POSTGRES" pg_isready -U sentinel -d sentinel

# pg_isready can report ready just before init.sql finishes; wait for the schema.
SCHEMA_READY=false
for _ in $(seq 1 90); do
  value="$(docker exec "$POSTGRES" psql -U sentinel -d sentinel -tAc \
    "SELECT 1 FROM schema_registry WHERE schema_name='image_message' AND schema_version='v1' AND is_active=TRUE" 2>/dev/null || true)"
  if [[ "$value" == '1' ]]; then
    SCHEMA_READY=true
    break
  fi
  sleep 2
done
[[ "$SCHEMA_READY" == true ]] || { echo 'FAIL: PostgreSQL schema registry not initialized'; exit 1; }
echo 'PASS: PostgreSQL schema registry initialized'

echo '===== STARTING PYTORCH 2.12.1 WORKER ====='
docker run --pull=never -d --name "$WORKER" \
  --network "$NETWORK" \
  -e RABBITMQ_HOST=rabbitmq \
  -e RABBITMQ_USERNAME=sentinel \
  -e RABBITMQ_PASSWORD=sentinel \
  -e REDIS_HOST=redis \
  -e POSTGRES_HOST=postgres \
  -e POSTGRES_DB=sentinel \
  -e POSTGRES_USER=sentinel \
  -e POSTGRES_PASSWORD=sentinel \
  -e WORKER_FEATURE_TTL_SECONDS=120 \
  -e AUTO_INFERENCE_ENABLED=false \
  "$WORKER_IMAGE" >/dev/null

READY=false
for _ in $(seq 1 90); do
  if [[ "$(docker inspect -f '{{.State.Running}}' "$WORKER")" != true ]]; then
    echo 'FAIL: Worker exited before it became ready'
    exit 1
  fi
  if docker logs "$WORKER" 2>&1 | grep -q 'Waiting for messages from queue'; then
    READY=true
    break
  fi
  sleep 2
done
[[ "$READY" == true ]] || { echo 'FAIL: Worker startup timeout'; exit 1; }
echo 'PASS: Worker started and subscribed to RabbitMQ'

echo '===== PRODUCING IMAGE AND CHECKING REDIS, POSTGRES AND DLQ ====='
docker run --pull=never --rm -i \
  --network "$NETWORK" \
  --entrypoint python "$WORKER_IMAGE" - <<'PY'
import base64
import json
import time
from io import BytesIO
from uuid import uuid4

import pika
import psycopg2
import redis
import torch
from PIL import Image

from sentinel.schema.v1 import ImageMessageV1

assert torch.__version__.split('+')[0] == '2.12.1'
print('PASS: E2E client PyTorch', torch.__version__, flush=True)

rabbit = pika.BlockingConnection(pika.ConnectionParameters(
    host='rabbitmq',
    credentials=pika.PlainCredentials('sentinel', 'sentinel'),
))
channel = rabbit.channel()
channel.queue_declare(queue='video_stream', passive=True)
channel.queue_declare(queue='video_stream.dlq', passive=True)

redis_client = redis.Redis(host='redis', decode_responses=False)
pg = psycopg2.connect(
    host='postgres', dbname='sentinel', user='sentinel', password='sentinel'
)

event_id = uuid4()
image_id = f'torch-2121-e2e-{uuid4().hex[:12]}'
image = Image.new('L', (28, 28), color=120)
buffer = BytesIO()
image.save(buffer, format='PNG')
image_bytes = buffer.getvalue()

message = ImageMessageV1(
    schema_version='v1',
    event_id=event_id,
    image_id=image_id,
    timestamp=time.time(),
    image_format='png',
    image_base64=base64.b64encode(image_bytes).decode('ascii'),
)
channel.basic_publish(
    exchange='', routing_key='video_stream',
    body=message.model_dump_json().encode('utf-8'),
    properties=pika.BasicProperties(delivery_mode=2, content_type='application/json'),
)
print('SENT: Valid PNG image:', image_id, flush=True)

key = f'feat:{image_id}'
row = None
redis_bytes = None
for _ in range(120):
    redis_bytes = redis_client.get(key)
    with pg.cursor() as cursor:
        cursor.execute(
            'SELECT raw_image, vector, model_version FROM feature_log WHERE event_id=%s',
            (str(event_id),),
        )
        row = cursor.fetchone()
    if row is not None and redis_bytes is not None:
        break
    time.sleep(1)

assert row is not None, 'PostgreSQL feature_log row missing'
assert redis_bytes is not None, 'Redis feature missing'
raw_image, vector, model_version = row
assert bytes(raw_image) == image_bytes, 'Persisted image differs'
assert model_version == 'v1', f'Unexpected model version: {model_version}'
assert len(vector) == 1 and len(vector[0]) == 1
assert len(vector[0][0]) == 28 and len(vector[0][0][0]) == 28
assert len(redis_bytes) == 28 * 28 * 4, 'Unexpected float32 tensor size'
ttl = redis_client.ttl(key)
assert 0 < ttl <= 120, f'Unexpected Redis TTL: {ttl}'
print('PASS: PostgreSQL feature_log (image + [1,1,28,28] tensor)', flush=True)
print('PASS: Redis feature bytes and configured TTL', ttl, flush=True)

invalid = b'{invalid-json-for-dlq'
channel.basic_publish(
    exchange='', routing_key='video_stream', body=invalid,
    properties=pika.BasicProperties(delivery_mode=2),
)
print('SENT: Invalid message for DLQ', flush=True)

dead_letter = None
for _ in range(90):
    method, properties, body = channel.basic_get(
        queue='video_stream.dlq', auto_ack=False
    )
    if method is not None:
        dead_letter = body
        assert dead_letter == invalid, 'DLQ body differs from rejected message'
        channel.basic_ack(method.delivery_tag)
        break
    time.sleep(1)
assert dead_letter is not None, 'Invalid message did not reach DLQ'
print('PASS: Invalid message rejected and delivered to DLQ', flush=True)

# At this point the only valid message has been processed and the invalid one
# dead-lettered, so the main queue must not have any pending/unacked messages.
queue = channel.queue_declare(queue='video_stream', passive=True).method
assert queue.message_count == 0, f'Main queue still has {queue.message_count} messages'
print('PASS: RabbitMQ main queue has no pending messages', flush=True)

pg.close()
redis_client.close()
rabbit.close()
print('SENTINEL PYTORCH 2.12.1 INGESTION E2E: ALL CHECKS PASSED', flush=True)
PY

echo '===== WORKER LOG SUMMARY ====='
docker logs --tail 20 "$WORKER" 2>&1

echo '===== E2E PASSED ====='
