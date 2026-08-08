"""Device-authenticated SaaS control-plane operations."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.models.db.control_plane import CameraProfile, DeviceCredential, EdgeDevice, ModelAssignment, Stream, Tenant
from backend.models.schemas.control_plane import CameraProfileCreate, DeviceCreate, ModelAssignmentCreate, StreamCreate, TenantCreate


def _hash_credential(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_tenant(db: Session, payload: TenantCreate) -> Tenant:
    existing = db.query(Tenant).filter(Tenant.tenant_key == payload.tenant_key).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="tenant_key already exists")
    tenant = Tenant(tenant_key=payload.tenant_key, name=payload.name)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


def create_device(db: Session, tenant_id: int, payload: DeviceCreate) -> tuple[EdgeDevice, str]:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active.is_(True)).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    existing = db.query(EdgeDevice).filter(
        EdgeDevice.tenant_id == tenant_id, EdgeDevice.device_key == payload.device_key
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="device_key already exists")
    device = EdgeDevice(tenant_id=tenant_id, device_key=payload.device_key, name=payload.name)
    raw_credential = secrets.token_urlsafe(32)
    credential = DeviceCredential(
        token_hash=_hash_credential(raw_credential),
        label=payload.credential_label,
        device=device,
    )
    db.add(device)
    db.add(credential)
    db.commit()
    db.refresh(device)
    return device, raw_credential


def authenticate_device(db: Session, raw_credential: str) -> tuple[EdgeDevice, Tenant]:
    if not raw_credential:
        raise HTTPException(status_code=401, detail="Device credential is required")
    credential = db.query(DeviceCredential).filter(
        DeviceCredential.token_hash == _hash_credential(raw_credential),
        DeviceCredential.is_active.is_(True),
        DeviceCredential.revoked_at.is_(None),
    ).first()
    if credential is None or credential.device is None or credential.device.tenant is None:
        raise HTTPException(status_code=401, detail="Invalid device credential")
    if credential.expires_at is not None and credential.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Device credential expired")
    if not credential.device.tenant.is_active:
        raise HTTPException(status_code=403, detail="Tenant is inactive")
    credential.last_used_at = datetime.now(timezone.utc)
    credential.device.last_seen_at = credential.last_used_at
    credential.device.status = "ONLINE"
    db.commit()
    return credential.device, credential.device.tenant


def create_stream(db: Session, device: EdgeDevice, payload: StreamCreate) -> Stream:
    if not payload.path.startswith(f"tenants/{device.tenant_id}/"):
        raise HTTPException(status_code=422, detail="Stream path must be tenant scoped")
    stream = Stream(
        tenant_id=device.tenant_id,
        device_id=device.id,
        camera_key=payload.camera_key,
        path=payload.path,
        protocol=payload.protocol,
    )
    db.add(stream)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Stream path already exists")
    db.refresh(stream)
    return stream


def create_profile(db: Session, device: EdgeDevice, payload: CameraProfileCreate) -> CameraProfile:
    allowed_toggles = {"zone", "fall", "ppe"}
    if set(payload.model_toggles) - allowed_toggles:
        raise HTTPException(status_code=422, detail="Unknown model toggle")
    protected = {
        "imgsz", "image_size", "confidence", "conf_thresh", "iou", "iou_thresh",
        "fall_threshold", "fall_max_frames", "queue_size", "fps", "width", "height",
    }
    if protected.intersection(payload.operational_config):
        raise HTTPException(status_code=422, detail="Quality-critical inference settings are protected")
    profile = CameraProfile(
        tenant_id=device.tenant_id,
        name=payload.name,
        model_toggles=payload.model_toggles,
        operational_config=payload.operational_config,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def assign_model(db: Session, device: EdgeDevice, payload: ModelAssignmentCreate) -> ModelAssignment:
    profile = db.query(CameraProfile).filter(
        CameraProfile.id == payload.profile_id,
        CameraProfile.tenant_id == device.tenant_id,
    ).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Camera profile not found")
    assignment = ModelAssignment(
        tenant_id=device.tenant_id,
        profile_id=profile.id,
        model_name=payload.model_name,
        model_version=payload.model_version,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment
