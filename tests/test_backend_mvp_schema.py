from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db.base import Base
from backend.models.db.camera import Camera
from backend.models.db.user import User
from backend.models.db.zone import Zone
from backend.models.schemas.auth import UserLogin, UserRegister
from backend.models.schemas.camera import (
    CameraCreate,
    CameraRuntimeConfigAck,
    CameraRuntimeRegistration,
    CameraUpdate,
)
from backend.models.schemas.event import CameraStatusRequest
from backend.models.schemas.zone import ZoneCreate
from backend.services.auth_service import auth_service
from backend.services.camera_service import camera_service
from backend.services.system_event_service import system_event_service
from backend.services.zone_service import zone_service


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)
    with local_session() as db:
        yield db
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_auth_uses_normalized_gmail_and_fixed_user_role(db_session):
    user = auth_service.register_user(
        db_session,
        UserRegister(gmail="  Safety.User@GMAIL.COM ", password="secret123"),
    )

    assert user.gmail == "safety.user@gmail.com"
    assert user.role == "USER"
    assert user.password_hash != "secret123"
    assert auth_service.authenticate_user(
        db_session,
        UserLogin(gmail="SAFETY.USER@gmail.com", password="secret123"),
    )
    assert db_session.query(User).one().gmail == "safety.user@gmail.com"

    with pytest.raises(ValidationError):
        UserRegister.model_validate(
            {
                "gmail": "safety.user@gmail.com",
                "password": "secret123",
                "role": "admin",
            }
        )
    with pytest.raises(ValidationError):
        UserRegister(gmail="user@example.com", password="secret123")


def test_camera_config_revision_and_runtime_registration_ownership(db_session):
    camera = camera_service.create_camera(
        db_session,
        CameraCreate(
            camera_key="cam-1",
            name="Gate camera",
            source="/data/fall.mp4",
            ppe_enabled=False,
        ),
    )
    assert camera.source_type == "VIDEO_FILE"
    assert camera.config_revision == 1
    assert camera.config_status == "OFFLINE"

    camera = camera_service.update_camera(
        db_session,
        camera.id,
        CameraUpdate(source="rtsp://camera/live", ppe_enabled=True),
    )
    assert camera.source_type == "RTSP"
    assert camera.ppe_enabled is True

    assert camera.config_revision == 2

    camera, created = camera_service.register_runtime_camera(
        db_session,
        camera.id,
        CameraRuntimeRegistration(
            camera_key="cam-1",
            name="Runtime camera",
            source="0",
            zone_enabled=False,
            fall_enabled=False,
            ppe_enabled=False,
        ),
    )
    assert created is False
    assert camera.source_type == "USB"
    assert camera.source == "0"
    assert camera.name == "Runtime camera"
    assert camera.zone_enabled is True
    assert camera.fall_enabled is True
    assert camera.ppe_enabled is True


def test_partial_model_update_does_not_overwrite_other_toggles(db_session):
    camera = camera_service.create_camera(
        db_session,
        CameraCreate(
            camera_key="cam-partial-toggle",
            name="Partial toggle camera",
            source="0",
            zone_enabled=True,
            fall_enabled=True,
            ppe_enabled=True,
        ),
    )

    camera = camera_service.update_camera(
        db_session,
        camera.id,
        CameraUpdate(fall_enabled=False),
    )

    assert camera.fall_enabled is False
    assert camera.zone_enabled is True
    assert camera.ppe_enabled is True
    assert camera.config_revision == 2


def test_zone_delete_is_soft_and_changes_camera_revision(db_session):
    camera = camera_service.create_camera(
        db_session,
        CameraCreate(camera_key="cam-zone", name="Zone camera", source="1"),
    )
    zone = zone_service.create_zone(
        db_session,
        ZoneCreate(
            camera_id=camera.id,
            name="Restricted",
            polygon_json=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
        ),
    )
    assert camera.config_revision == 2

    zone_service.delete_zone(db_session, zone.id)

    persisted = db_session.get(Zone, zone.id)
    assert persisted is not None
    assert persisted.deleted_at is not None
    assert persisted.is_active is False
    assert zone_service.get_zone_by_id(db_session, zone.id) is None
    assert zone_service.get_zones(db_session, camera_id=camera.id) == []
    assert camera.config_revision == 3


def test_camera_status_updates_last_seen_and_config_state(db_session):
    camera = camera_service.create_camera(
        db_session,
        CameraCreate(camera_key="cam-status", name="Status camera", source="2"),
    )
    observed_at = datetime.now(timezone.utc)
    system_event_service.ingest_camera_status(
        db_session,
        CameraStatusRequest(
            event_id="922f13ce-09ab-46ea-bd30-3af3d4e4f980",
            event_category="CAMERA_STATUS",
            camera_id=camera.id,
            status="ONLINE",
            observed_time=observed_at,
            source="TEST",
        ),
    )
    db_session.refresh(camera)
    assert camera.status == "ONLINE"
    assert camera.config_status == "PENDING"
    assert camera.last_seen_at is not None
    assert camera.last_seen_at.replace(tzinfo=timezone.utc) == observed_at


def test_runtime_config_includes_active_zones_and_acknowledges_revision(db_session):
    camera = camera_service.create_camera(
        db_session,
        CameraCreate(camera_key="runtime-config", name="Runtime", source="0"),
    )
    zone_service.create_zone(
        db_session,
        ZoneCreate(
            camera_id=camera.id,
            name="Restricted",
            polygon_json=[[0.1, 0.1], [0.9, 0.1], [0.5, 0.9]],
        ),
    )
    runtime_config = camera_service.get_runtime_config(db_session, camera.id)
    assert runtime_config.revision == 2
    assert runtime_config.zones[0].name == "Restricted"

    acknowledged = camera_service.acknowledge_runtime_config(
        db_session,
        camera.id,
        CameraRuntimeConfigAck(
            revision=2,
            status="APPLIED",
            zone_enabled=True,
            fall_enabled=True,
            ppe_enabled=False,
        ),
    )
    assert acknowledged.status == "ONLINE"
    assert acknowledged.config_status == "APPLIED"
    assert acknowledged.applied_revision == 2


def test_runtime_config_rejects_stale_ack(db_session):
    camera = camera_service.create_camera(
        db_session,
        CameraCreate(camera_key="stale-ack", name="Stale", source="0"),
    )
    camera_service.update_camera(
        db_session, camera.id, CameraUpdate(ppe_enabled=True)
    )
    with pytest.raises(HTTPException) as exc_info:
        camera_service.acknowledge_runtime_config(
            db_session,
            camera.id,
            CameraRuntimeConfigAck(
                revision=1,
                status="APPLIED",
                zone_enabled=True,
                fall_enabled=True,
                ppe_enabled=False,
            ),
        )
    assert exc_info.value.status_code == 409
