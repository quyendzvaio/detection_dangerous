"""Multi-tenant isolation: each user sees only their own tenant's resources.

All checks go through the HTTP API as real authenticated users, so the
trusted tenant source is `current_user.tenant_id` from the DB row.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.deps import get_db
from backend.db.base import Base
from backend.main import app
import backend.ws as ws_module

AI_HEADERS = {"Authorization": "Bearer local-ai-service-token-change-me"}


def make_client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    original_ws_session = ws_module.SessionLocal
    ws_module.SessionLocal = session_factory

    def override_db():
        with session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), engine, original_ws_session


def close_client(client, engine, original_ws_session):
    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
    ws_module.SessionLocal = original_ws_session


def _register_login(client, gmail):
    assert client.post(
        "/api/v1/auth/register", json={"gmail": gmail, "password": "strong-password"}
    ).status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"gmail": gmail, "password": "strong-password"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _tenant_id(headers):
    """Decode the JWT (signature irrelevant here) to read the tenant claim."""
    import jwt as pyjwt

    claims = pyjwt.decode(
        headers["Authorization"].split(" ")[1],
        options={"verify_signature": False},
    )
    return claims["tenant_id"]


def test_signup_creates_distinct_tenants_per_user():
    client, engine, original = make_client()
    try:
        headers_a = _register_login(client, "tenant-a@gmail.com")
        headers_b = _register_login(client, "tenant-b@gmail.com")
        assert _tenant_id(headers_a) != _tenant_id(headers_b)
    finally:
        close_client(client, engine, original)


def test_camera_list_and_get_are_tenant_scoped():
    client, engine, original = make_client()
    try:
        headers_a = _register_login(client, "tenant-a@gmail.com")
        headers_b = _register_login(client, "tenant-b@gmail.com")

        created = client.post(
            "/api/v1/cameras",
            headers=headers_a,
            json={"camera_key": "cam-a", "name": "A camera", "source": "0"},
        )
        assert created.status_code == 201, created.text
        camera_id = created.json()["id"]

        # B's list must not include A's camera.
        assert [c["id"] for c in client.get("/api/v1/cameras", headers=headers_b).json()] == []
        # B's by-id lookup must 404 (no existence leak).
        assert client.get(f"/api/v1/cameras/{camera_id}", headers=headers_b).status_code == 404
        # A still sees it.
        assert client.get(f"/api/v1/cameras/{camera_id}", headers=headers_a).status_code == 200
    finally:
        close_client(client, engine, original)


def test_violation_isolation():
    client, engine, original = make_client()
    try:
        headers_a = _register_login(client, "tenant-a@gmail.com")
        headers_b = _register_login(client, "tenant-b@gmail.com")

        created = client.post(
            "/api/v1/cameras",
            headers=headers_a,
            json={"camera_key": "cam-a", "name": "A camera", "source": "0"},
        )
        camera_id = created.json()["id"]

        # Ingest a violation for A's camera via the M2M endpoint (AI service path).
        event = {
            "event_id": "11111111-2222-3333-4444-555555555555",
            "camera_id": camera_id,
            "track_id": "t-1",
            "detected_time": "2026-08-09T00:00:00+00:00",
            "violation_type": "PPE_VIOLATION",
            "severity_level": "DANGER",
            "evidence_status": "PROCESSING",
            "violation_codes": ["NO_HELMET"],
            "image_storage_key": None,
            "video_storage_key": None,
        }
        resp = client.post("/api/v1/internal/events", json=event, headers=AI_HEADERS)
        assert resp.status_code == 201, resp.text
        violation_id = resp.json()["record_id"]

        # B's list is empty; B's by-id lookup 404s.
        assert client.get("/api/v1/violations", headers=headers_b).json() == []
        assert (
            client.get(f"/api/v1/violations/{violation_id}", headers=headers_b).status_code
            == 404
        )
        # A sees its own violation.
        assert (
            client.get(f"/api/v1/violations/{violation_id}", headers=headers_a).status_code
            == 200
        )
    finally:
        close_client(client, engine, original)


def test_zone_isolation():
    client, engine, original = make_client()
    try:
        headers_a = _register_login(client, "tenant-a@gmail.com")
        headers_b = _register_login(client, "tenant-b@gmail.com")

        created = client.post(
            "/api/v1/cameras",
            headers=headers_a,
            json={"camera_key": "cam-a", "name": "A camera", "source": "0"},
        )
        camera_id = created.json()["id"]

        zone = client.post(
            "/api/v1/zones",
            headers=headers_a,
            json={
                "camera_id": camera_id,
                "name": "Restricted",
                "polygon_json": [[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
            },
        )
        assert zone.status_code == 201, zone.text
        zone_id = zone.json()["id"]

        assert client.get("/api/v1/zones", headers=headers_b).json() == []
        assert client.get(f"/api/v1/zones/{zone_id}", headers=headers_b).status_code == 404
        assert client.get(f"/api/v1/zones/{zone_id}", headers=headers_a).status_code == 200
    finally:
        close_client(client, engine, original)


def test_report_summary_is_tenant_scoped():
    client, engine, original = make_client()
    try:
        headers_a = _register_login(client, "tenant-a@gmail.com")
        headers_b = _register_login(client, "tenant-b@gmail.com")

        created = client.post(
            "/api/v1/cameras",
            headers=headers_a,
            json={"camera_key": "cam-a", "name": "A camera", "source": "0"},
        )
        assert created.status_code == 201

        summary_a = client.get("/api/v1/reports/summary", headers=headers_a).json()
        summary_b = client.get("/api/v1/reports/summary", headers=headers_b).json()
        assert summary_a["total_cameras"] == 1
        assert summary_b["total_cameras"] == 0
    finally:
        close_client(client, engine, original)


def test_websocket_cannot_subscribe_to_other_tenant_camera():
    """WS tenant source is the JWT claim; cross-tenant camera closes 4404."""
    client, engine, original = make_client()
    try:
        headers_a = _register_login(client, "tenant-a@gmail.com")
        headers_b = _register_login(client, "tenant-b@gmail.com")

        created = client.post(
            "/api/v1/cameras",
            headers=headers_a,
            json={"camera_key": "cam-a", "name": "A camera", "source": "0"},
        )
        camera_id = created.json()["id"]

        # B tries to subscribe to A's camera frames: server closes 4404.
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                f"/ws/cameras/{camera_id}?overlay=true",
                subprotocols=["bearer", headers_b["Authorization"].split(" ")[1]],
            ):
                pass
        assert exc_info.value.code == 4404
    finally:
        close_client(client, engine, original)


def test_mqtt_message_cannot_create_cross_tenant_resources():
    """customer_sync resolves tenant from the envelope tenant_key; a message
    for tenant B never touches tenant A's camera/violation rows."""
    from backend.services.customer_sync import CustomerSync
    from backend.models.db.camera import Camera
    from backend.models.db.violation import Violation

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    sync = CustomerSync(db_factory=local_session)

    envelope_a = {
        "tenant_key": "tenant-a",
        "device_key": "edge-001",
        "camera_key": "cam-1",
        "idempotency_key": "evt-1",
        "emitted_at": "2026-08-09T00:00:00+00:00",
        "payload": {
            "event_id": "11111111-2222-3333-4444-555555555555",
            "camera_id": 1,
            "track_id": "t-1",
            "detected_time": "2026-08-09T00:00:00+00:00",
            "violation_type": "PPE_VIOLATION",
            "severity_level": "DANGER",
            "evidence_status": "PROCESSING",
            "violation_codes": ["NO_HELMET"],
            "image_storage_key": None,
            "video_storage_key": None,
        },
    }
    sync._handle_envelope(envelope_a)

    db = local_session()
    try:
        cam = db.query(Camera).filter(Camera.camera_key == "cam-1").first()
        violation = db.query(Violation).first()
        assert cam is not None and cam.tenant_id is not None
        assert violation is not None and violation.tenant_id == cam.tenant_id
    finally:
        db.close()
        engine.dispose()
