from typing import List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.db.violation import Violation
from backend.models.schemas.violation import ViolationCreate, PresignedUrlOut
from backend.services.storage_service import storage_service


class ViolationService:
    @staticmethod
    def get_violations(
        db: Session,
        camera_id: Optional[int] = None,
        violation_type: Optional[str] = None,
        severity_level: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[Violation]:
        query = db.query(Violation).filter(Violation.deleted_at.is_(None))
        if camera_id:
            query = query.filter(Violation.camera_id == camera_id)
        if violation_type:
            query = query.filter(Violation.violation_type == violation_type)
        if severity_level:
            query = query.filter(Violation.severity_level == severity_level)
        
        return query.order_by(Violation.detected_time.desc()).offset(skip).limit(limit).all()

    @staticmethod
    def get_violation_by_id(db: Session, violation_id: int) -> Optional[Violation]:
        return db.query(Violation).filter(Violation.id == violation_id, Violation.deleted_at.is_(None)).first()

    @staticmethod
    def create_violation(db: Session, violation_in: ViolationCreate) -> Violation:
        violation = Violation(
            camera_id=violation_in.camera_id,
            violation_type=violation_in.violation_type,
            severity_level=violation_in.severity_level or "WARNING",
            worker_code=violation_in.worker_code,
            video_bucket=violation_in.video_bucket,
            video_path=violation_in.video_path,
            image_path=violation_in.image_path,
            status="NEW",
            ai_metadata=violation_in.ai_metadata
        )
        db.add(violation)
        db.commit()
        db.refresh(violation)
        return violation

    @staticmethod
    def get_presigned_urls(db: Session, violation_id: int, expires_in_seconds: int = 3600) -> PresignedUrlOut:
        violation = ViolationService.get_violation_by_id(db, violation_id)
        if not violation:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Violation not found")

        video_url = storage_service.generate_presigned_url(violation.video_path, expires_seconds=expires_in_seconds)
        image_url = storage_service.generate_presigned_url(violation.image_path, expires_seconds=expires_in_seconds)

        return PresignedUrlOut(
            violation_id=violation.id,
            video_url=video_url,
            image_url=image_url,
            expires_in_seconds=expires_in_seconds
        )


violation_service = ViolationService()
