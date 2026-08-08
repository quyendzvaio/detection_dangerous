from datetime import datetime, timezone

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


def test_authenticated_product_runtime_control_and_live_frame_flow():
    client, engine, original_ws_session = make_client()
    try:
        assert client.get("/api/v1/cameras").status_code == 401
        assert client.post(
            "/api/v1/auth/register",
            json={"gmail": "operator@gmail.com", "password": "strong-password"},
        ).status_code == 201
        login = client.post(
            "/api/v1/auth/login",
            json={"gmail": "operator@gmail.com", "password": "strong-password"},
        )
        access_token = login.json()["access_token"]
        user_headers = {"Authorization": f"Bearer {access_token}"}

        created = client.post(
            "/api/v1/cameras",
            headers=user_headers,
            json={
                "camera_key": "api-cam",
                "name": "API Camera",
                "source": "rtsp://operator:secret@camera.local/stream",
            },
        )
        assert created.status_code == 201
        assert created.json()["source"] == "rtsp://***:***@camera.local/stream"
        camera_id = created.json()["id"]

        toggled = client.patch(
            f"/api/v1/cameras/{camera_id}/models",
            headers=user_headers,
            json={"ppe_enabled": True, "fall_enabled": True, "zone_enabled": False},
        )
        revision = toggled.json()["config_revision"]
        zone = client.post(
            "/api/v1/zones",
            headers=user_headers,
            json={
                "camera_id": camera_id,
                "name": "Loading bay",
                "polygon_json": [[0.1, 0.1], [0.8, 0.1], [0.5, 0.8]],
                "is_active": True,
            },
        )
        assert zone.status_code == 201
        revision += 1
        runtime = client.get(
            f"/api/v1/internal/cameras/{camera_id}/runtime-config",
            headers=AI_HEADERS,
        )
        assert runtime.json()["ppe_enabled"] is True
        assert runtime.json()["zones"][0]["name"] == "Loading bay"

        ack = client.post(
            f"/api/v1/internal/cameras/{camera_id}/runtime-config/ack",
            headers=AI_HEADERS,
            json={
                "revision": revision,
                "status": "APPLIED",
                "ppe_enabled": True,
                "fall_enabled": True,
                "zone_enabled": False,
            },
        )
        assert ack.json()["config_status"] == "APPLIED"

        telemetry = client.post(
            f"/api/v1/internal/cameras/{camera_id}/telemetry",
            headers=AI_HEADERS,
            json={
                "processing_fps": 24.5,
                "latency_ms": 31.2,
                "last_frame_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        assert telemetry.status_code == 200
        assert telemetry.json()["processing_fps"] == 24.5

        jpeg = b"\xff\xd8product-frame\xff\xd9"
        assert client.post(
            f"/api/v1/internal/cameras/{camera_id}/frame?overlay=true",
            headers={**AI_HEADERS, "Content-Type": "image/jpeg"},
            content=jpeg,
        ).status_code == 204
        frame = client.get(
            f"/api/v1/cameras/{camera_id}/stream?overlay=true", headers=user_headers
        )
        assert frame.status_code == 200
        assert frame.content == jpeg
        assert frame.headers["content-type"] == "image/jpeg"

        with client.websocket_connect(
            f"/ws/cameras/{camera_id}?overlay=true",
            subprotocols=["bearer", access_token],
        ) as websocket:
            live_jpeg = b"\xff\xd8live-frame\xff\xd9"
            pushed = client.post(
                f"/api/v1/internal/cameras/{camera_id}/frame?overlay=true",
                headers={**AI_HEADERS, "Content-Type": "image/jpeg"},
                content=live_jpeg,
            )
            assert pushed.status_code == 204
            assert websocket.receive_bytes() == live_jpeg

        with client.websocket_connect(
            "/ws/alerts", subprotocols=["bearer", access_token]
        ) as websocket:
            status_event = client.post(
                "/api/v1/internal/camera-status",
                headers=AI_HEADERS,
                json={
                    "event_id": "09a019e5-279c-48dd-8fe8-a135f94bd859",
                    "event_category": "CAMERA_STATUS",
                    "camera_id": camera_id,
                    "status": "ONLINE",
                    "observed_time": datetime.now(timezone.utc).isoformat(),
                    "source": "TEST",
                },
            )
            assert status_event.status_code == 201
            realtime = websocket.receive_json()
            assert realtime["event_category"] == "CAMERA_STATUS"
            assert realtime["message_id"]
            assert realtime["data"]["camera_id"] == camera_id
    finally:
        close_client(client, engine, original_ws_session)
