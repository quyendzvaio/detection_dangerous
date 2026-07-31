#!/usr/bin/env bash
set -euo pipefail

# Product-path smoke test. Repeat --camera for independent camera processes.
# Examples:
#   ./run_pipeline_demo.sh --camera 1:cam1:0 --show
#   ./run_pipeline_demo.sh --camera 1:gate:rtsp://host/stream --show
#   ./run_pipeline_demo.sh --camera 1:test:/absolute/path/test.mp4 --show
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TRITON_HTTP_URL="${TRITON_HTTP_URL:-http://localhost:8000}"
TRITON_START_TIMEOUT="${TRITON_START_TIMEOUT:-60}"

cd "$PROJECT_ROOT"
docker compose up -d triton-server

echo "[pipeline] Waiting for Triton, yolo_pose and fall_model..."
for ((attempt = 1; attempt <= TRITON_START_TIMEOUT; attempt++)); do
  if curl --fail --silent "$TRITON_HTTP_URL/v2/health/ready" >/dev/null 2>&1 && \
     curl --fail --silent "$TRITON_HTTP_URL/v2/models/yolo_pose/ready" >/dev/null 2>&1 && \
     curl --fail --silent "$TRITON_HTTP_URL/v2/models/fall_model/ready" >/dev/null 2>&1; then
    echo "[pipeline] Triton is ready."
    break
  fi
  if ((attempt == TRITON_START_TIMEOUT)); then
    echo "[pipeline] Triton models were not ready after ${TRITON_START_TIMEOUT}s." >&2
    echo "[pipeline] Check: docker compose logs --tail=200 triton-server" >&2
    exit 1
  fi
  sleep 1
done

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m ai_engine.pipeline.runner \
  --layer2-models "${LAYER2_MODELS:-zone,fall}" "$@"
