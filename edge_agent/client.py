"""Minimal outbound edge-agent control loop primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class EdgeAgentConfig:
    control_plane_url: str
    device_credential: str
    timeout_seconds: float = 5.0


class EdgeAgentClient:
    def __init__(self, config: EdgeAgentConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"X-Device-Credential": config.device_credential})

    def heartbeat(self) -> dict[str, Any]:
        response = self.session.post(
            f"{self.config.control_plane_url.rstrip('/')}/api/v1/control/devices/heartbeat",
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def get_config(self) -> dict[str, Any]:
        response = self.session.get(
            f"{self.config.control_plane_url.rstrip('/')}/api/v1/control/devices/config",
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.session.close()

