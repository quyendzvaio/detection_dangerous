from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.db.camera import Camera
from backend.models.db.violation import Violation
from backend.models.db.zone import Zone
from backend.models.schemas.event import (
    FallDetectedRequest,
    FallSuspectedRequest,
    PPEViolationRequest,
    RestrictedZoneRequest,
    SafetyEventRequest,
)
from backend.models.schemas.violation import PresignedUrlOut
from backend.services.storage_service import storage_service


class ViolationService:
    @staticmethod
    def get_violations(
        db: Session,
        camera_id: int | None = None,
        violation_type: str | None = None,
        severity_level: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Violation]:
        query = db.query(Violation).filter(Violation.deleted_at.is_(None))
        if camera_id is not None:
            query = query.filter(Violation.camera_id == camera_id)
        if violation_type is not None:
            query = query.filter(Violation.violation_type == violation_type)
        if severity_level is not None:
            query = query.filter(Violation.severity_level == severity_level)
        return (
            query.order_by(Violation.detected_time.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def get_violation_by_id(db: Session, violation_id: int) -> Violation | None:
        return (
            db.query(Violation)
            .filter(Violation.id == violation_id, Violation.deleted_at.is_(None))
            .first()
        )

    @staticmethod
    def ingest_event(
        db: Session, event: SafetyEventRequest
    ) -> tuple[Violation, bool]:
        existing = (
            db.query(Violation).filter(Violation.event_id == event.event_id).first()
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

        zone_id = None
        confidence = None
        violation_codes = None
        if isinstance(event, RestrictedZoneRequest):
            zone = (
                db.query(Zone)
                .filter(Zone.id == event.zone_id, Zone.camera_id == event.camera_id)
                .first()
            )
            if zone is None:
                raise HTTPException(status_code=404, detail="Zone not found for camera")
            zone_id = event.zone_id
        elif isinstance(event, (FallDetectedRequest, FallSuspectedRequest)):
            confidence = event.confidence
        elif isinstance(event, PPEViolationRequest):
            violation_codes = list(event.violation_codes)

        detected_time = event.detected_time
        if detected_time.tzinfo is None:
            detected_time = detected_time.replace(tzinfo=timezone.utc)

        violation = Violation(
            event_id=event.event_id,
            camera_id=event.camera_id,
            track_id=event.track_id,
            detected_time=detected_time,
            violation_type=event.violation_type,
            severity_level=event.severity_level,
            confidence=confidence,
            zone_id=zone_id,
            violation_codes=violation_codes,
            evidence_status=event.evidence_status,
            image_storage_key=event.image_storage_key,
            video_storage_key=event.video_storage_key,
            status="NEW",
        )
        db.add(violation)
        try:
            db.commit()
            db.refresh(violation)
            return violation, True
        except IntegrityError:
            db.rollback()
            duplicate = (
                db.query(Violation)
                .filter(Violation.event_id == event.event_id)
                .first()
            )
            if duplicate is None:
                raise
            return duplicate, False

    @staticmethod
    def update_status(
        db: Session, violation_id: int, new_status: str, reviewer_id: int
    ) -> Violation:
        violation = ViolationService.get_violation_by_id(db, violation_id)
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        violation.status = new_status
        violation.reviewed_by = reviewer_id
        violation.reviewed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(violation)
        return violation

    @staticmethod
    def get_presigned_urls(
        db: Session, violation_id: int, expires_in_seconds: int = 3600
    ) -> PresignedUrlOut:
        violation = ViolationService.get_violation_by_id(db, violation_id)
        if violation is None:
            raise HTTPException(status_code=404, detail="Violation not found")
        return PresignedUrlOut(
            violation_id=violation.id,
            video_url=storage_service.generate_signed_download(
                violation.video_storage_key, expires_seconds=expires_in_seconds
            ),
            image_url=storage_service.generate_signed_download(
                violation.image_storage_key, expires_seconds=expires_in_seconds
            ),
            expires_in_seconds=expires_in_seconds,
        )


violation_service = ViolationService()
