from datetime import timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.db.camera import Camera
from backend.models.db.system_event import SystemEvent
from backend.models.schemas.event import CameraStatusRequest


class SystemEventService:
    @staticmethod
    def ingest_camera_status(
        db: Session, event: CameraStatusRequest
    ) -> tuple[SystemEvent, bool]:
        existing = (
            db.query(SystemEvent).filter(SystemEvent.event_id == event.event_id).first()
        )
        if existing is not None:
            return existing, False

        camera = (
            db.query(Camera)
            .filter(Camera.id == event.camera_id, Camera.deleted_at.is_(None))
            .first()
        )
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")

        observed_at = event.observed_time
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        record = SystemEvent(
            event_id=event.event_id,
            camera_id=event.camera_id,
            status=event.status,
            observed_at=observed_at,
            reason=event.reason,
            source=event.source,
        )
        camera.status = event.status
        camera.last_seen_at = observed_at
        if event.status == "OFFLINE":
            camera.config_status = "OFFLINE"
        elif camera.applied_revision == camera.config_revision:
            camera.config_status = "APPLIED"
        else:
            camera.config_status = "PENDING"
        db.add(record)
        try:
            db.commit()
            db.refresh(record)
            return record, True
        except IntegrityError:
            db.rollback()
            duplicate = (
                db.query(SystemEvent)
                .filter(SystemEvent.event_id == event.event_id)
                .first()
            )
            if duplicate is None:
                raise
            return duplicate, False


system_event_service = SystemEventService()
