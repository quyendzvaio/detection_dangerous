#!/usr/bin/env bash
set -euo pipefail

# Starts the project Triton service, waits for yolo_pose, then runs the Layer 1 demo.
# Example:
#   ./run_layer1_demo.sh --camera 1:cam1:0 --camera 2:cam2:2 --show
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRITON_HTTP_URL="${TRITON_HTTP_URL:-http://localhost:8000}"
TRITON_START_TIMEOUT="${TRITON_START_TIMEOUT:-60}"

cd "$PROJECT_ROOT"
docker compose up -d triton-server

echo "[layer1] Waiting for Triton and model yolo_pose..."
for ((attempt = 1; attempt <= TRITON_START_TIMEOUT; attempt++)); do
  if curl --fail --silent --show-error "$TRITON_HTTP_URL/v2/health/ready" >/dev/null 2>&1 && \
     curl --fail --silent --show-error "$TRITON_HTTP_URL/v2/models/yolo_pose/ready" >/dev/null 2>&1; then
    echo "[layer1] Triton is ready: yolo_pose loaded."
    break
  fi
  if ((attempt == TRITON_START_TIMEOUT)); then
    echo "[layer1] Triton/yolo_pose was not ready after ${TRITON_START_TIMEOUT}s." >&2
    echo "[layer1] Inspect logs with: docker compose logs --tail=200 triton-server" >&2
    exit 1
  fi
  sleep 1
done

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m ai_engine.testing.layer1_demo "$@"
