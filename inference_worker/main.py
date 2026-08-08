"""Launch server-side inference from a JSON camera assignment list.

The worker receives stream URLs from control-plane configuration. It never
opens a local USB device or accepts a customer inbound connection.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from ai_engine.pipeline.runner import main as pipeline_main
from edge_agent.messaging import PahoMqttTransport


def _probe_control_plane() -> None:
    import requests

    base_url = os.environ["CONTROL_PLANE_URL"].rstrip("/") + "/"
    response = requests.get(urljoin(base_url, "health/ready"), timeout=5)
    response.raise_for_status()


def _probe_triton() -> None:
    import tritonclient.grpc as grpcclient

    client = grpcclient.InferenceServerClient(url=os.environ["TRITON_URL"])
    if not client.is_server_ready():
        raise RuntimeError("Triton is not ready")


def _probe_mqtt() -> None:
    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")
    if (username is None) != (password is None) or username is None:
        raise RuntimeError("MQTT_USERNAME and MQTT_PASSWORD are required")
    transport = PahoMqttTransport(
        os.environ["MQTT_HOST"],
        int(os.environ.get("MQTT_PORT", "8883")),
        username=username,
        password=password,
        tls_ca_file=os.environ.get("MQTT_CA_FILE") or None,
    )
    transport.close()


def _probe_required_services() -> None:
    _probe_control_plane()
    _probe_triton()
    _probe_mqtt()


def _mark_ready() -> None:
    ready_file = Path(os.environ.get("WORKER_READY_FILE", "/tmp/visionguard-worker-ready"))
    ready_file.touch()


def main() -> int:
    raw = os.getenv("INFERENCE_CAMERAS", "[]")
    try:
        cameras = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"INFERENCE_CAMERAS must be valid JSON: {exc}") from exc
    if not isinstance(cameras, list):
        raise SystemExit("INFERENCE_CAMERAS must be a JSON list")

    try:
        _probe_required_services()
    except Exception as exc:
        raise SystemExit(f"Required service connectivity failed: {exc}") from exc

    if not cameras:
        print("NO_CAMERA_CONFIGURED", flush=True)
        _mark_ready()
        while True:
            time.sleep(60)

    argv = ["--media-mtx-only", "--skip-camera-registration"]
    for item in cameras:
        if not isinstance(item, dict) or not all(
            key in item for key in ("id", "key", "stream")
        ):
            raise SystemExit("Each INFERENCE_CAMERAS item requires id, key and stream")
        argv.extend(["--camera", f"{int(item['id'])}:{item['key']}:{item['stream']}"])

    _mark_ready()
    return pipeline_main(argv)


if __name__ == "__main__":
    sys.exit(main())
