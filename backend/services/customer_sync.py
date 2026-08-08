"""Customer-host MQTT sync: ingest cloud violation events into local PostgreSQL.

Runs as a background thread inside the local backend. Subscribes to the
customer tenant's event topic, then writes violations + evidence through the
same services the HTTP API uses, so the frontend sees cloud events without
any SQLite side-channel.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session
from pydantic import TypeAdapter

from backend.core.config import settings
from backend.db.session import SessionLocal
from backend.models.schemas.event import SafetyEventRequest
from backend.services.camera_service import camera_service
from backend.services.violation_service import violation_service

log = logging.getLogger(__name__)

# SafetyEventRequest is a discriminated union; TypeAdapter gives it a
# model_validate without needing FastAPI.
_event_adapter = TypeAdapter(SafetyEventRequest)


class CustomerSync:
    """One MQTT subscription -> local DB writer, started on app lifespan."""

    def __init__(self, db_factory=SessionLocal) -> None:
        self.db_factory = db_factory
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(
            settings.DEPLOYMENT_ROLE == "customer-host"
            and os.environ.get("MQTT_HOST")
            and os.environ.get("MQTT_USERNAME")
        )

    def _connect(self):
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        client.username_pw_set(
            os.environ["MQTT_USERNAME"], os.environ.get("MQTT_PASSWORD")
        )
        ca_file = os.environ.get("MQTT_CA_FILE")
        if ca_file and Path(ca_file).exists():
            client.tls_set(ca_certs=ca_file, cert_reqs=ssl.CERT_REQUIRED)
        client.on_message = self._on_message
        self._client = client
        return client

    def _on_message(self, _client, _userdata, message) -> None:
        # Fire-and-forget: a bad message must not take down the consumer.
        try:
            self._handle_envelope(json.loads(message.payload))
        except Exception as exc:  # noqa: BLE001
            log.warning("customer sync: invalid message: %s", exc)

    def _handle_envelope(self, envelope: dict[str, Any]) -> None:
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("envelope payload must be an object")
        db: Session = self.db_factory()
        try:
            # Evidence-completion message: payload has event_id + READY status
            # and the storage keys are actually signed download URLs.
            if (
                "evidence_status" in payload
                and payload.get("evidence_status") == "READY"
                and "camera_id" not in payload
            ):
                self._sync_evidence_message(db, envelope)
                return

            # 1. Ensure the camera exists locally (map by camera_id).
            camera_id = int(payload["camera_id"])
            if not self._ensure_camera(db, camera_id, envelope):
                log.info(
                    "customer sync: camera_id=%s missing, skipping event %s",
                    camera_id,
                    payload.get("event_id"),
                )
                return

            # 2. Idempotent ingest (duplicates are no-ops).
            event = _event_adapter.validate_python(payload)
            violation, created = violation_service.ingest_event(db, event)
            if created:
                log.info(
                    "customer sync: ingested %s violation_id=%s event_id=%s",
                    event.violation_type,
                    violation.id,
                    event.event_id,
                )
        finally:
            db.close()

    def _sync_evidence_message(self, db: Session, envelope: dict) -> None:
        """Handle the worker's second MQTT message carrying evidence URLs."""
        from uuid import UUID

        from backend.models.db.violation import Violation

        payload = envelope.get("payload") or {}
        event_id = UUID(str(payload["event_id"]))
        violation = (
            db.query(Violation).filter(Violation.event_id == event_id).first()
        )
        if violation is None or violation.evidence_status == "READY":
            return
        evidence_dir = Path(os.environ.get("EVIDENCE_LOCAL_DIR", "/data/evidence"))
        image_url = payload.get("image_storage_key")
        video_url = payload.get("video_storage_key")
        downloaded = []
        if image_url:
            target = evidence_dir / str(violation.id) / "image.jpg"
            if self._download(image_url, target):
                downloaded.append(target)
                violation.image_storage_key = f"local://{target}"
        if video_url:
            target = evidence_dir / str(violation.id) / "video.mp4"
            if self._download(video_url, target):
                downloaded.append(target)
                violation.video_storage_key = f"local://{target}"
        if downloaded:
            violation.evidence_status = "READY"
            db.commit()
            log.info(
                "customer sync: evidence ready for violation %s (%s files)",
                violation.id,
                len(downloaded),
            )

    def _ensure_camera(self, db: Session, camera_id: int, envelope: dict) -> bool:
        from backend.models.db.camera import Camera

        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        if camera is not None and camera.deleted_at is None:
            return True
        if camera is None:
            # Auto-register from the envelope camera_key so the camera shows in the UI.
            from backend.models.schemas.camera import CameraRuntimeRegistration

            try:
                registration = CameraRuntimeRegistration(
                    camera_key=str(envelope["camera_key"]),
                    name=f"Camera {camera_id}",
                    source=f"cloud://camera-{camera_id}",
                    source_type="RTSP",
                )
                camera, _created = camera_service.register_runtime_camera(
                    db, camera_id, registration
                )
                log.info(
                    "customer sync: registered camera_id=%s key=%s",
                    camera_id,
                    registration.camera_key,
                )
                return True
            except Exception as exc:  # noqa: BLE001
                log.warning("customer sync: camera registration failed: %s", exc)
                return False
        return False


    @staticmethod
    def _download(url: str, target: Path) -> bool:
        import requests

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                log.warning("customer sync: evidence download HTTP %s", response.status_code)
                return False
            response.raise_for_status()
            target.write_bytes(response.content)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("customer sync: evidence download failed: %s", exc)
            return False

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(
            target=self._run, name="customer-sync", daemon=True
        )
        self._thread.start()
        log.info("customer sync: MQTT consumer started")

    def _run(self) -> None:
        try:
            client = self._connect()
        except Exception as exc:  # noqa: BLE001
            log.error("customer sync: MQTT init failed: %s", exc)
            return
        tenant_key = os.environ.get("TENANT_KEY", "")
        device_key = os.environ.get("DEVICE_KEY", "")
        topic = f"events/{tenant_key}/{device_key}/#"
        try:
            client.connect(
                os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "8883"))
            )
            client.subscribe(topic, qos=0)
            client.loop_forever()
        except Exception as exc:  # noqa: BLE001
            log.error("customer sync: MQTT loop failed: %s", exc)
        finally:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass


customer_sync = CustomerSync()
