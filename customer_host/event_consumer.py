"""Local MQTT consumer with idempotent, non-reconciling event storage."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

import requests


class LocalEventStore:
    """Small local store; production customer backend can use the same contract."""

    def __init__(self, database_path: str = "customer_events.sqlite3"):
        self.connection = sqlite3.connect(database_path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS received_events (
                idempotency_key TEXT PRIMARY KEY,
                tenant_key TEXT NOT NULL,
                device_key TEXT NOT NULL,
                camera_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                evidence_status TEXT NOT NULL DEFAULT 'PENDING'
            )"""
        )
        self.connection.commit()

    def insert_once(self, envelope: dict[str, Any]) -> bool:
        cursor = self.connection.execute(
            """INSERT OR IGNORE INTO received_events
            (idempotency_key, tenant_key, device_key, camera_key, payload_json)
            VALUES (?, ?, ?, ?, ?)""",
            (
                envelope["idempotency_key"],
                envelope["tenant_key"],
                envelope["device_key"],
                envelope["camera_key"],
                json.dumps(envelope["payload"], separators=(",", ":"), sort_keys=True),
            ),
        )
        self.connection.commit()
        return cursor.rowcount == 1

    def close(self) -> None:
        self.connection.close()


@dataclass(frozen=True)
class EvidenceDownloadResult:
    status: str
    reason: str | None = None


class CustomerEventConsumer:
    """Consumes one MQTT message; never asks SaaS for a replacement URL."""

    def __init__(self, store: LocalEventStore, timeout_seconds: float = 10.0):
        self.store = store
        self.timeout_seconds = timeout_seconds

    def handle_message(self, payload: bytes | str) -> bool:
        envelope = json.loads(payload)
        required = {"tenant_key", "device_key", "camera_key", "idempotency_key", "payload"}
        if not required.issubset(envelope):
            raise ValueError("MQTT envelope is missing required fields")
        return self.store.insert_once(envelope)

    def download_evidence_once(self, signed_url: str) -> EvidenceDownloadResult:
        try:
            response = requests.get(signed_url, timeout=self.timeout_seconds)
            if response.status_code == 200:
                return EvidenceDownloadResult("READY")
            if response.status_code in {401, 403, 404}:
                return EvidenceDownloadResult("FAILED", f"HTTP {response.status_code}; URL may be expired")
            return EvidenceDownloadResult("FAILED", f"HTTP {response.status_code}")
        except requests.RequestException as exc:
            return EvidenceDownloadResult("FAILED", str(exc))

