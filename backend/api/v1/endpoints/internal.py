import hmac
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, Response
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.deps import get_db
from backend.models.schemas.camera import (
    CameraOut,
    CameraRuntimeConfig,
    CameraRuntimeConfigAck,
    CameraRuntimeRegistration,
    CameraTelemetryIn,
    CameraTelemetryOut,
)
from backend.models.schemas.evidence import (
    EvidenceCompleteRequest,
    EvidenceFailRequest,
    EvidenceLifecycleResponse,
    EvidencePresignRequest,
    EvidencePresignResponse,
)
from backend.models.schemas.event import (
    CameraStatusRequest,
    EventIngestResponse,
    SafetyEventRequest,
)
from backend.services.camera_service import camera_service
from backend.services.evidence_service import evidence_service
from backend.services.system_event_service import system_event_service
from backend.services.violation_service import violation_service
from backend.ws import alerts_manager, camera_frames_manager
from backend.frame_store import latest_frames

router = APIRouter()


def require_ai_service(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {settings.AI_SERVICE_TOKEN}"
    if authorization is None or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid AI service credentials")


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def register_runtime_camera(
    camera_id: int,
    payload: CameraRuntimeRegistration,
    response: Response,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    if camera_id <= 0:
        raise HTTPException(status_code=422, detail="camera_id must be positive")
    camera, created = camera_service.register_runtime_camera(db, camera_id, payload)
    response.status_code = 201 if created else 200
    return camera


@router.get(
    "/cameras/{camera_id}/runtime-config", response_model=CameraRuntimeConfig
)
def get_runtime_config(
    camera_id: int,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    return camera_service.get_runtime_config(db, camera_id)


@router.post(
    "/cameras/{camera_id}/runtime-config/ack", response_model=CameraOut
)
def acknowledge_runtime_config(
    camera_id: int,
    payload: CameraRuntimeConfigAck,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    camera = camera_service.acknowledge_runtime_config(db, camera_id, payload)
    background_tasks.add_task(
        alerts_manager.broadcast,
        {
            "event_category": "CONFIG_STATUS",
            "camera_id": camera.id,
            "revision": camera.applied_revision,
            "status": camera.config_status,
            "error": camera.config_error,
        },
    )
    return camera


@router.post("/cameras/{camera_id}/telemetry", response_model=CameraTelemetryOut)
def update_camera_telemetry(
    camera_id: int,
    payload: CameraTelemetryIn,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    return camera_service.update_telemetry(db, camera_id, payload)


@router.post("/cameras/{camera_id}/frame", status_code=204)
async def update_camera_frame(
    camera_id: int,
    request: Request,
    overlay: bool = True,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    if camera_service.get_camera_by_id(db, camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if request.headers.get("content-type", "").split(";", 1)[0] != "image/jpeg":
        raise HTTPException(status_code=415, detail="Frame must be image/jpeg")
    jpeg = await request.body()
    if not jpeg or len(jpeg) > 5_000_000:
        raise HTTPException(status_code=413, detail="Frame must be between 1 byte and 5 MB")
    latest_frames.put(camera_id, overlay, jpeg)
    await camera_frames_manager.broadcast(camera_id, overlay, jpeg)
    return Response(status_code=204)


@router.post("/events", response_model=EventIngestResponse)
async def receive_safety_event(
    payload: SafetyEventRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    violation, created = violation_service.ingest_event(db, payload)
    response.status_code = 201 if created else 200
    if created:
        message = payload.model_dump(mode="json")
        message.update({"record_id": violation.id, "record_status": violation.status})
        background_tasks.add_task(alerts_manager.broadcast, message)
    return EventIngestResponse(
        status="created" if created else "duplicate",
        event_id=violation.event_id,
        record_id=violation.id,
    )


@router.post("/camera-status", response_model=EventIngestResponse)
async def receive_camera_status(
    payload: CameraStatusRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    record, created = system_event_service.ingest_camera_status(db, payload)
    response.status_code = 201 if created else 200
    if created:
        message = payload.model_dump(mode="json")
        message.update({"record_id": record.id})
        background_tasks.add_task(alerts_manager.broadcast, message)
    return EventIngestResponse(
        status="created" if created else "duplicate",
        event_id=record.event_id,
        record_id=record.id,
    )


@router.post(
    "/events/{event_id}/evidence/presign",
    response_model=EvidencePresignResponse,
)
def presign_evidence_uploads(
    event_id: UUID,
    payload: EvidencePresignRequest,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    return evidence_service.request_uploads(db, event_id, payload)


@router.post(
    "/events/{event_id}/evidence/complete",
    response_model=EvidenceLifecycleResponse,
)
async def complete_evidence_uploads(
    event_id: UUID,
    payload: EvidenceCompleteRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    result = evidence_service.complete_uploads(db, event_id, payload)
    background_tasks.add_task(
        alerts_manager.broadcast,
        {"event_category": "EVIDENCE_STATUS", **result.model_dump(mode="json")},
    )
    return result


@router.post(
    "/events/{event_id}/evidence/fail",
    response_model=EvidenceLifecycleResponse,
)
async def fail_evidence_uploads(
    event_id: UUID,
    payload: EvidenceFailRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _authorized: None = Depends(require_ai_service),
):
    result = evidence_service.fail_uploads(db, event_id, payload)
    background_tasks.add_task(
        alerts_manager.broadcast,
        {"event_category": "EVIDENCE_STATUS", **result.model_dump(mode="json")},
    )
    return result
