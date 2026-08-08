#!/usr/bin/env bash
set -euo pipefail

# USB example:
#   ./run_layer0_multi.sh --camera 1:cam1:0 --camera 2:cam2:2 --show
# Simulate a slow next layer:
#   ./run_layer0_multi.sh --camera 1:cam1:0 --camera 2:cam2:2 --consumer-delay-ms 150
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m ai_engine.ingest.layer0_multi_runner "$@"
