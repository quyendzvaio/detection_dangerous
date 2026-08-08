from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.base import Base
from backend.models.schemas.control_plane import CameraProfileCreate, DeviceCreate, StreamCreate, TenantCreate
from backend.services.control_plane_service import (
    authenticate_device,
    create_device,
    create_stream,
    create_profile,
    create_tenant,
)


def test_device_credential_scopes_stream_to_its_tenant():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant_a = create_tenant(db, TenantCreate(tenant_key="tenant-a", name="A"))
        tenant_b = create_tenant(db, TenantCreate(tenant_key="tenant-b", name="B"))
        device, raw = create_device(
            db, tenant_a.id, DeviceCreate(device_key="edge-a", name="Edge A")
        )
        stream = create_stream(
            db,
            device,
            StreamCreate(camera_key="cam-1", path="tenants/1/cameras/1/main"),
        )
        assert stream.tenant_id == tenant_a.id
        authenticated_device, authenticated_tenant = authenticate_device(db, raw)
        assert authenticated_device.id == device.id
        assert authenticated_tenant.id == tenant_a.id
        assert authenticated_tenant.id != tenant_b.id


def test_stream_path_must_be_tenant_scoped():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = create_tenant(db, TenantCreate(tenant_key="tenant-a", name="A"))
        device, _ = create_device(
            db, tenant.id, DeviceCreate(device_key="edge-a", name="Edge A")
        )
        try:
            create_stream(db, device, StreamCreate(camera_key="cam-1", path="tenants/999/cameras/1/main"))
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 422
        else:
            raise AssertionError("cross-tenant stream path was accepted")


def test_profile_cannot_override_quality_critical_settings():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = create_tenant(db, TenantCreate(tenant_key="tenant-a", name="A"))
        device, _ = create_device(db, tenant.id, DeviceCreate(device_key="edge-a", name="Edge A"))
        try:
            create_profile(
                db,
                device,
                CameraProfileCreate(name="unsafe", operational_config={"confidence": 0.01}),
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 422
        else:
            raise AssertionError("quality-critical profile setting was accepted")
