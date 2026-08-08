"""Launch server-side inference from a JSON camera assignment list.

The worker receives stream URLs from control-plane configuration. It never
opens a local USB device or accepts a customer inbound connection.
"""
from __future__ import annotations

import json
import os
import sys

from ai_engine.pipeline.runner import main as pipeline_main


def main() -> int:
    raw = os.getenv("INFERENCE_CAMERAS", "[]")
    try:
        cameras = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"INFERENCE_CAMERAS must be valid JSON: {exc}") from exc
    if not isinstance(cameras, list) or not cameras:
        raise SystemExit("INFERENCE_CAMERAS must contain at least one camera assignment")

    argv = ["--media-mtx-only", "--skip-camera-registration"]
    for item in cameras:
        if not isinstance(item, dict) or not all(
            key in item for key in ("id", "key", "stream")
        ):
            raise SystemExit("Each INFERENCE_CAMERAS item requires id, key and stream")
        argv.extend(["--camera", f"{int(item['id'])}:{item['key']}:{item['stream']}"])

    return pipeline_main(argv)


if __name__ == "__main__":
    sys.exit(main())
