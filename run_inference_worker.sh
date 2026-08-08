#!/usr/bin/env bash
set -euo pipefail

# Server-side inference entrypoint. Every source must be a MediaMTX RTSP/RTSPS
# path; this flag makes accidental USB/file ingestion fail fast.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m ai_engine.pipeline.runner --media-mtx-only "$@"

