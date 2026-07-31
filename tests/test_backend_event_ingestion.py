from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_engine.contracts.event_schema import (
    CameraStatus,
    CameraStatusEvent,
    FallDetectedEvent,
)
from backend.core.deps import get_db
from backend.db.base import Base
from backend.main import app
from backend.models.db.camera import Camera
from backend.models.db.system_event import SystemEvent
from backend.models.db.violation import Violation
from backend.storage import UploadLease

TOKEN = "local-ai-service-token-change-me"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
NOW = 1_700_000_000.0


def make_test_app():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    def override_db():
        db = local_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), local_session, engine


def close_test_app(client, engine):
    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def register_camera(client):
    return client.put(
        "/api/v1/internal/cameras/1",
        headers=HEADERS,
        json={
            "camera_key": "cam1",
            "name": "Camera 1",
            "source": "0",
            "zone_enabled": True,
            "fall_enabled": True,
            "ppe_enabled": False,
        },
    )


def test_typed_fall_event_is_persisted_once():
    client, local_session, engine = make_test_app()
    try:
        assert register_camera(client).status_code == 201
        event = FallDetectedEvent(
            camera_id=1,
            track_id="cam1-3",
            detected_at=NOW,
            confidence=0.93,
        )
        first = client.post(
            "/api/v1/internal/events",
            headers=HEADERS,
            json=event.to_backend_payload(),
        )
        duplicate = client.post(
            "/api/v1/internal/events",
            headers=HEADERS,
            json=event.to_backend_payload(),
        )
        assert first.status_code == 201
        assert first.json()["status"] == "created"
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "duplicate"
        with local_session() as db:
            records = db.query(Violation).all()
            assert len(records) == 1
            assert records[0].confidence == 0.93
            assert records[0].severity_level == "CRITICAL"
    finally:
        close_test_app(client, engine)


def test_contract_rejects_removed_schema_fields_and_unknown_camera():
    client, _, engine = make_test_app()
    try:
        payload = FallDetectedEvent(
            camera_id=2,
            track_id="cam2-1",
            detected_at=NOW,
            confidence=0.8,
        ).to_backend_payload()
        payload["schema_version"] = "1.0"
        assert client.post(
            "/api/v1/internal/events", headers=HEADERS, json=payload
        ).status_code == 422
        payload.pop("schema_version")
        assert client.post(
            "/api/v1/internal/events", headers=HEADERS, json=payload
        ).status_code == 404
    finally:
        close_test_app(client, engine)


def test_camera_status_has_separate_table_and_updates_current_status():
    client, local_session, engine = make_test_app()
    try:
        assert register_camera(client).status_code == 201
        event = CameraStatusEvent(
            camera_id=1,
            status=CameraStatus.ONLINE,
            observed_at=NOW,
            reason="first frame",
            source="CAMERA_PROCESS",
        )
        response = client.post(
            "/api/v1/internal/camera-status",
            headers=HEADERS,
            json=event.to_backend_payload(),
        )
        assert response.status_code == 201
        with local_session() as db:
            assert db.query(SystemEvent).count() == 1
            assert db.get(Camera, 1).status == "ONLINE"
            assert db.query(Violation).count() == 0
    finally:
        close_test_app(client, engine)


def test_fall_evidence_presign_and_complete_lifecycle(monkeypatch):
    from backend.services.storage_service import storage_service

    monkeypatch.setattr(
        storage_service,
        "create_upload_lease",
        lambda key, content_type, expires_seconds=None: UploadLease(
            url=f"https://azure.example/{key}?signed=1",
            headers={"x-ms-blob-type": "BlockBlob"},
            expires_in_seconds=900,
        ),
    )
    monkeypatch.setattr(
        storage_service,
        "verify_uploaded_object",
        lambda key, expected_size, expected_content_type: {
            "size_bytes": expected_size,
            "etag": "verified-etag",
            "content_type": expected_content_type,
        },
    )
    client, local_session, engine = make_test_app()
    try:
        assert register_camera(client).status_code == 201
        event = FallDetectedEvent(
            camera_id=1,
            track_id="cam1-5",
            detected_at=NOW,
            confidence=0.96,
        )
        assert client.post(
            "/api/v1/internal/events", headers=HEADERS, json=event.to_backend_payload()
        ).status_code == 201

        presign = client.post(
            f"/api/v1/internal/events/{event.event_id}/evidence/presign",
            headers=HEADERS,
            json={
                "objects": [
                    {"kind": "IMAGE", "content_type": "image/jpeg", "size_bytes": 1200},
                    {"kind": "VIDEO", "content_type": "video/mp4", "size_bytes": 6400},
                ]
            },
        )
        assert presign.status_code == 200, presign.text
        uploads = presign.json()["uploads"]
        assert {item["kind"] for item in uploads} == {"IMAGE", "VIDEO"}
        assert all(item["upload_url"].startswith("https://azure.example/") for item in uploads)
        assert all(str(event.event_id) in item["object_key"] for item in uploads)

        complete = client.post(
            f"/api/v1/internal/events/{event.event_id}/evidence/complete",
            headers=HEADERS,
            json={
                "objects": [
                    {
                        "evidence_id": item["evidence_id"],
                        "size_bytes": 1200 if item["kind"] == "IMAGE" else 6400,
                        "etag": '"abc123"',
                    }
                    for item in uploads
                ]
            },
        )
        assert complete.status_code == 200, complete.text
        body = complete.json()
        assert body["evidence_status"] == "READY"
        assert body["image_storage_key"].endswith("/image.jpg")
        assert body["video_storage_key"].endswith("/video.mp4")
        assert {item["status"] for item in body["objects"]} == {"READY"}
        with local_session() as db:
            record = db.query(Violation).one()
            assert record.evidence_status == "READY"
            assert len(record.evidence_objects) == 2
    finally:
        close_test_app(client, engine)


def test_ppe_evidence_rejects_video(monkeypatch):
    from ai_engine.contracts.event_schema import PPEViolationEvent, PpeViolationCode
    from backend.services.storage_service import storage_service

    monkeypatch.setattr(
        storage_service,
        "create_upload_lease",
        lambda key, content_type, expires_seconds=None: UploadLease(
            url="https://azure.example/upload",
            headers={"x-ms-blob-type": "BlockBlob"},
            expires_in_seconds=900,
        ),
    )
    client, _, engine = make_test_app()
    try:
        assert register_camera(client).status_code == 201
        event = PPEViolationEvent(
            camera_id=1,
            track_id="cam1-6",
            detected_at=NOW,
            violation_codes=(PpeViolationCode.NO_HELMET,),
        )
        assert client.post(
            "/api/v1/internal/events", headers=HEADERS, json=event.to_backend_payload()
        ).status_code == 201
        response = client.post(
            f"/api/v1/internal/events/{event.event_id}/evidence/presign",
            headers=HEADERS,
            json={
                "objects": [
                    {"kind": "VIDEO", "content_type": "video/mp4", "size_bytes": 1000}
                ]
            },
        )
        assert response.status_code == 422
    finally:
        close_test_app(client, engine)
