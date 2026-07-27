#!/usr/bin/env bash
set -euo pipefail

# Example: ./run_layer0_demo.sh --source 0 --show
# Slow-consumer test: ./run_layer0_demo.sh --source 0 --consumer-delay-ms 150
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$PROJECT_ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m ai_engine.ingest.layer0_runner "$@"
