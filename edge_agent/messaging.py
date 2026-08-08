"""Outbound-only MQTT message contracts and fire-and-forget publisher."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class MqttTopic:
    kind: str
    tenant_key: str
    device_key: str
    camera_key: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"events", "config", "status"}:
            raise ValueError("kind must be events, config or status")
        values = (self.kind, self.tenant_key, self.device_key, self.camera_key)
        if any(value is not None and ("/" in value or not value) for value in values):
            raise ValueError("MQTT topic segments cannot be empty or contain '/'")
        if self.kind != "status" and not self.camera_key:
            raise ValueError("events/config topics require camera_key")

    def __str__(self) -> str:
        segments = [self.kind, self.tenant_key, self.device_key]
        if self.camera_key:
            segments.append(self.camera_key)
        return "/".join(segments)


@dataclass(frozen=True)
class MessageEnvelope:
    tenant_key: str
    device_key: str
    camera_key: str
    idempotency_key: str
    payload: dict[str, Any]
    emitted_at: str = ""

    def to_json(self) -> bytes:
        emitted_at = self.emitted_at or datetime.now(timezone.utc).isoformat()
        return json.dumps(
            {
                "tenant_key": self.tenant_key,
                "device_key": self.device_key,
                "camera_key": self.camera_key,
                "idempotency_key": self.idempotency_key,
                "emitted_at": emitted_at,
                # The existing SafetyEvent payload is kept byte-for-byte
                # semantically intact inside this transport envelope.
                "payload": self.payload,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")


class MqttTransport(Protocol):
    def publish(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None: ...


class FireAndForgetPublisher:
    """QoS 0/non-retained publisher; no retry or offline queue by design."""

    def __init__(self, transport: MqttTransport):
        self.transport = transport

    def publish(self, topic: MqttTopic, envelope: MessageEnvelope) -> bool:
        try:
            self.transport.publish(str(topic), envelope.to_json(), qos=0, retain=False)
        except Exception:
            return False
        return True


class PahoMqttTransport:
    """Small optional adapter; paho is imported only when the edge agent runs."""

    def __init__(
        self,
        host: str,
        port: int = 8883,
        username: str | None = None,
        password: str | None = None,
        tls: bool = True,
        tls_ca_file: str | None = None,
    ):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:  # pragma: no cover - exercised in edge image
            raise RuntimeError("Install paho-mqtt to run the MQTT edge transport") from exc
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        if (username is None) != (password is None):
            raise ValueError("MQTT_USERNAME and MQTT_PASSWORD must be provided together")
        if username is not None:
            self._client.username_pw_set(username, password)
        if tls:
            if tls_ca_file is not None and not Path(tls_ca_file).is_file():
                raise FileNotFoundError(f"MQTT CA file does not exist: {tls_ca_file}")
            self._client.tls_set(
                ca_certs=tls_ca_file,
                cert_reqs=ssl.CERT_REQUIRED,
            )
        self._client.connect(host, port)
        self._client.loop_start()

    def publish(self, topic: str, payload: bytes, *, qos: int = 0, retain: bool = False) -> None:
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        if info.rc != 0:
            raise RuntimeError(f"MQTT publish failed with code {info.rc}")

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
