from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.deps import get_db
from backend.models.db.control_plane import EdgeDevice, Stream, Tenant
from backend.models.schemas.control_plane import (
    DeviceConfigOut,
    CameraProfileCreate,
    CameraProfileOut,
    DeviceCreate,
    DeviceCredentialOut,
    DeviceStatusOut,
    StreamCreate,
    StreamOut,
    ModelAssignmentCreate,
    ModelAssignmentOut,
    TenantCreate,
    TenantOut,
)
from backend.services.control_plane_service import (
    authenticate_device,
    create_device,
    create_profile,
    assign_model,
    create_stream,
    create_tenant,
)
from fastapi import HTTPException, status

router = APIRouter()


def require_bootstrap_token(token: str | None = Header(default=None, alias="X-Control-Plane-Bootstrap-Token")) -> None:
    if not settings.CONTROL_PLANE_BOOTSTRAP_TOKEN or token != settings.CONTROL_PLANE_BOOTSTRAP_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid control-plane bootstrap token")


def require_device(
    credential: str | None = Header(default=None, alias="X-Device-Credential"),
    db: Session = Depends(get_db),
) -> tuple[EdgeDevice, Tenant]:
    return authenticate_device(db, credential or "")


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def provision_tenant(payload: TenantCreate, db: Session = Depends(get_db), _=Depends(require_bootstrap_token)):
    return create_tenant(db, payload)


@router.post("/tenants/{tenant_id}/devices", response_model=DeviceCredentialOut, status_code=status.HTTP_201_CREATED)
def provision_device(tenant_id: int, payload: DeviceCreate, db: Session = Depends(get_db), _=Depends(require_bootstrap_token)):
    device, credential = create_device(db, tenant_id, payload)
    return DeviceCredentialOut(
        device_id=device.id,
        tenant_id=device.tenant_id,
        device_key=device.device_key,
        credential=credential,
    )


@router.post("/devices/heartbeat", response_model=DeviceStatusOut)
def heartbeat(identity=Depends(require_device)):
    device, tenant = identity
    return DeviceStatusOut(device_id=device.id, tenant_id=tenant.id, status="ONLINE", last_seen_at=device.last_seen_at)


@router.get("/devices/config", response_model=DeviceConfigOut)
def get_device_config(identity=Depends(require_device), db: Session = Depends(get_db)):
    device, tenant = identity
    streams = db.query(Stream).filter(Stream.device_id == device.id, Stream.tenant_id == tenant.id).order_by(Stream.id).all()
    return DeviceConfigOut(device_id=device.id, tenant_id=tenant.id, streams=streams)


@router.post("/devices/streams", response_model=StreamOut, status_code=status.HTTP_201_CREATED)
def register_stream(payload: StreamCreate, identity=Depends(require_device), db: Session = Depends(get_db)):
    device, _tenant = identity
    return create_stream(db, device, payload)


@router.post("/devices/profiles", response_model=CameraProfileOut, status_code=status.HTTP_201_CREATED)
def register_profile(payload: CameraProfileCreate, identity=Depends(require_device), db: Session = Depends(get_db)):
    device, _tenant = identity
    return create_profile(db, device, payload)


@router.post("/devices/model-assignments", response_model=ModelAssignmentOut, status_code=status.HTTP_201_CREATED)
def register_model_assignment(payload: ModelAssignmentCreate, identity=Depends(require_device), db: Session = Depends(get_db)):
    device, _tenant = identity
    return assign_model(db, device, payload)


@router.post("/media-auth", include_in_schema=False)
async def media_auth(request: Request, db: Session = Depends(get_db)):
    """MediaMTX external auth callback, scoped by device credential and path."""
    from backend.services.control_plane_service import authenticate_device

    payload = await request.json()
    raw_credential = str(payload.get("password") or payload.get("token") or "")
    device, tenant = authenticate_device(db, raw_credential)
    path = str(payload.get("path") or "")
    action = str(payload.get("action") or "")
    stream = db.query(Stream).filter(
        Stream.tenant_id == tenant.id,
        Stream.device_id == device.id,
        Stream.path == path,
    ).first()
    if stream is None or action not in {"publish", "read"}:
        raise HTTPException(status_code=403, detail="Stream access denied")
    return {"status": "authorized", "tenant_id": tenant.id, "device_id": device.id}
