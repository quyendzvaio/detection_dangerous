#!/usr/bin/env bash
set -euo pipefail

# Product-path smoke test. Repeat --camera for independent camera processes.
# Examples:
#   ./run_pipeline_demo.sh --camera 1:cam1:0 --show
#   ./run_pipeline_demo.sh --camera 1:gate:rtsp://host/stream --show
#   ./run_pipeline_demo.sh --camera 1:test:/absolute/path/test.mp4 --show
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

TRITON_HTTP_URL="${TRITON_HTTP_URL:-http://localhost:8000}"
BACKEND_HTTP_URL="${BACKEND_HTTP_URL:-http://localhost:${BACKEND_PORT:-8080}}"
BACKEND_EVENT_URL="${BACKEND_EVENT_URL:-${BACKEND_HTTP_URL}/api/v1/internal/events}"
AI_SERVICE_TOKEN="${AI_SERVICE_TOKEN:-local-ai-service-token-change-me}"
SERVICE_START_TIMEOUT="${SERVICE_START_TIMEOUT:-90}"

EVIDENCE_MODE="${EVIDENCE_ENABLED:-auto}"
EVIDENCE_ARGS=()
if [[ "$EVIDENCE_MODE" == "1" || "$EVIDENCE_MODE" == "true" || "$EVIDENCE_MODE" == "auto" ]]; then
  if [[ -z "${AZURE_STORAGE_CONNECTION_STRING:-}" ]]; then
    echo "[pipeline] Evidence is enabled but AZURE_STORAGE_CONNECTION_STRING is missing." >&2
    echo "[pipeline] Put the Azure Storage connection string in .env, or set EVIDENCE_ENABLED=0." >&2
    exit 1
  fi
  EVIDENCE_ARGS+=(--evidence)
fi

docker compose up -d --build postgres adminer backend frontend triton-server

echo "[pipeline] Waiting for backend/PostgreSQL..."
for ((attempt = 1; attempt <= SERVICE_START_TIMEOUT; attempt++)); do
  if curl --fail --silent "$BACKEND_HTTP_URL/health/ready" >/dev/null 2>&1; then
    echo "[pipeline] Backend and PostgreSQL are ready."
    break
  fi
  if ((attempt == SERVICE_START_TIMEOUT)); then
    echo "[pipeline] Backend was not ready after ${SERVICE_START_TIMEOUT}s." >&2
    echo "[pipeline] Check: docker compose logs --tail=200 backend postgres" >&2
    exit 1
  fi
  sleep 1
done

echo "[pipeline] Waiting for Triton, yolo_pose and fall_model..."
for ((attempt = 1; attempt <= SERVICE_START_TIMEOUT; attempt++)); do
  if curl --fail --silent "$TRITON_HTTP_URL/v2/health/ready" >/dev/null 2>&1 && \
     curl --fail --silent "$TRITON_HTTP_URL/v2/models/yolo_pose/ready" >/dev/null 2>&1 && \
     curl --fail --silent "$TRITON_HTTP_URL/v2/models/fall_model/ready" >/dev/null 2>&1; then
    echo "[pipeline] Triton is ready."
    break
  fi
  if ((attempt == SERVICE_START_TIMEOUT)); then
    echo "[pipeline] Triton models were not ready after ${SERVICE_START_TIMEOUT}s." >&2
    echo "[pipeline] Check: docker compose logs --tail=200 triton-server" >&2
    exit 1
  fi
  sleep 1
done

if ((${#EVIDENCE_ARGS[@]})); then
  echo "[pipeline] Azure Blob Cloud evidence capture is enabled."
else
  echo "[pipeline] Azure Blob evidence capture is disabled; set EVIDENCE_ENABLED=1 to enable it."
fi

echo "[pipeline] Adminer: http://localhost:${ADMINER_PORT:-8081}"
echo "[pipeline] Product UI: http://localhost:${FRONTEND_PORT:-3000}"
# Azure connection credentials are backend-only. Do not leak them into camera child processes.
unset AZURE_STORAGE_CONNECTION_STRING

if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m ai_engine.pipeline.runner \
  --backend-event-url "$BACKEND_EVENT_URL" \
  --ai-service-token "$AI_SERVICE_TOKEN" \
  --layer2-models "${LAYER2_MODELS:-zone,fall}" \
  "${EVIDENCE_ARGS[@]}" "$@"
