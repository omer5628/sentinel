#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "${HELM_PLUGIN_DIR}/../../.." && pwd)"

exec uv run --project "$REPO_ROOT" python \
    "${HELM_PLUGIN_DIR}/renderer.py"
