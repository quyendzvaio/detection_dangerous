"""Unit tests for the customer-host MQTT -> PostgreSQL sync service."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.models.db.camera import Camera
from backend.models.db.violation import Violation
from backend.services.customer_sync import CustomerSync


def make_sync() -> tuple[CustomerSync, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    sync = CustomerSync(db_factory=local_session)
    return sync, local_session


def _ppe_envelope(camera_key: str = "cam-1", camera_id: int = 1) -> dict:
    return {
        "tenant_key": "customer-a",
        "device_key": "edge-001",
        "camera_key": camera_key,
        "idempotency_key": "evt-1",
        "emitted_at": "2026-08-08T00:00:00+00:00",
        "payload": {
            "event_id": "11111111-2222-3333-4444-555555555555",
            "camera_id": camera_id,
            "track_id": "t-1",
            "detected_time": "2026-08-08T00:00:00+00:00",
            "violation_type": "PPE_VIOLATION",
            "severity_level": "DANGER",
            "evidence_status": "PROCESSING",
            "violation_codes": ["NO_HELMET"],
            "image_storage_key": None,
            "video_storage_key": None,
        },
    }


def test_envelope_ingests_violation_and_creates_camera():
    sync, session = make_sync()
    sync._handle_envelope(_ppe_envelope())

    db = session()
    camera = db.query(Camera).filter(Camera.camera_key == "cam-1").first()
    assert camera is not None, "camera should be auto-created from envelope"
    assert camera.id == 1

    violation = db.query(Violation).filter(Violation.camera_id == 1).first()
    assert violation is not None
    assert violation.violation_type == "PPE_VIOLATION"
    assert violation.violation_codes == ["NO_HELMET"]
    db.close()


def test_duplicate_envelope_is_idempotent():
    sync, session = make_sync()
    sync._handle_envelope(_ppe_envelope())
    sync._handle_envelope(_ppe_envelope())

    db = session()
    assert db.query(Violation).count() == 1
    db.close()


def test_missing_camera_key_envelope_is_skipped_not_crash():
    sync, session = make_sync()
    envelope = _ppe_envelope()
    del envelope["camera_key"]
    # Fire-and-forget: a malformed envelope must not raise out of the handler.
    sync._handle_envelope(envelope)
    db = session()
    assert db.query(Violation).count() == 0
    db.close()


def test_evidence_message_flips_violation_ready_with_local_urls(tmp_path, monkeypatch):
    """Module connectivity: event envelope -> DB -> evidence message -> local files
    -> presigned URL served by the backend (customer-host, no Azure)."""
    from backend.services.violation_service import violation_service

    def fake_download(url: str, target: Path) -> bool:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"jpeg-bytes")
        return True

    sync, session = make_sync()
    sync._handle_envelope(_ppe_envelope())
    db = session()
    violation = db.query(Violation).one()
    assert violation.evidence_status == "PROCESSING"
    db.close()

    monkeypatch.setattr(CustomerSync, "_download", staticmethod(fake_download))
    monkeypatch.setenv("EVIDENCE_LOCAL_DIR", str(tmp_path))
    sync._handle_envelope(
        {
            "tenant_key": "customer-a",
            "device_key": "edge-001",
            "camera_key": "cam-1",
            "idempotency_key": "evt-1:evidence",
            "emitted_at": "2026-08-08T00:00:00+00:00",
            "payload": {
                "event_id": "11111111-2222-3333-4444-555555555555",
                "evidence_status": "READY",
                "image_storage_key": "https://saas.example/signed/image.jpg?sig=1",
                "video_storage_key": None,
            },
        }
    )

    db = session()
    violation = db.query(Violation).one()
    assert violation.evidence_status == "READY"
    assert violation.image_storage_key == f"local://{tmp_path}/1/image.jpg"
    assert (tmp_path / "1" / "image.jpg").read_bytes() == b"jpeg-bytes"

    urls = violation_service.get_presigned_urls(db, violation.tenant_id, violation.id)
    assert urls.image_url == "/api/v1/violations/1/evidence/image"
    assert urls.video_url is None
    db.close()
