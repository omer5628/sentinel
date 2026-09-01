#!/bin/bash

set -euo pipefail

TARGET_ROOT="/home/.docker_data"
DOCKER_DEFAULTS="/etc/default/docker"
TARGET_OPTS='DOCKER_OPTS="--data-root /home/.docker_data --mtu=1460"'

if [ "${GOOGLE_CLOUD_WORKSTATIONS:-}" != "true" ]; then
    echo "Docker persistence check skipped: not running in Google Cloud Workstations."
    exit 0
fi

echo "Checking Docker persistent data root..."

ACTIVE_ROOT="$(
    docker info \
        --format '{{.DockerRootDir}}' \
        2>/dev/null || true
)"

if [ "${ACTIVE_ROOT}" = "${TARGET_ROOT}" ]; then
    echo "Docker persistence verified: ${TARGET_ROOT}"
    exit 0
fi

echo "Docker is using an unexpected data root."
echo "Expected: ${TARGET_ROOT}"
echo "Actual:   ${ACTIVE_ROOT:-unavailable}"

echo "Applying persistent Docker configuration..."

sudo install \
    -d \
    -m 0711 \
    -o root \
    -g root \
    "${TARGET_ROOT}"

sudo sed -i '/^DOCKER_OPTS=/d' "${DOCKER_DEFAULTS}"

echo "${TARGET_OPTS}" \
    | sudo tee -a "${DOCKER_DEFAULTS}" \
    >/dev/null

echo "Restarting Docker..."

sudo service docker restart

for _ in $(seq 1 60); do
    if docker info >/dev/null 2>&1; then
        break
    fi

    sleep 1
done

ACTIVE_ROOT="$(
    docker info \
        --format '{{.DockerRootDir}}' \
        2>/dev/null || true
)"

if [ "${ACTIVE_ROOT}" != "${TARGET_ROOT}" ]; then
    echo "ERROR: Docker persistence verification failed."
    echo "Expected: ${TARGET_ROOT}"
    echo "Actual:   ${ACTIVE_ROOT:-unavailable}"
    exit 1
fi

echo "Docker persistence restored: ${TARGET_ROOT}"
