from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.db.camera import Camera
from backend.models.schemas.camera import (
    CameraCreate,
    CameraRuntimeRegistration,
    CameraUpdate,
)


class CameraService:
    @staticmethod
    def get_all_cameras(db: Session, include_deleted: bool = False) -> list[Camera]:
        query = db.query(Camera)
        if not include_deleted:
            query = query.filter(Camera.deleted_at.is_(None))
        return query.order_by(Camera.id).all()

    @staticmethod
    def get_camera_by_id(db: Session, camera_id: int) -> Camera | None:
        return (
            db.query(Camera)
            .filter(Camera.id == camera_id, Camera.deleted_at.is_(None))
            .first()
        )

    @staticmethod
    def create_camera(db: Session, camera_in: CameraCreate) -> Camera:
        camera = Camera(**camera_in.model_dump())
        db.add(camera)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="camera_key already exists",
            ) from exc
        db.refresh(camera)
        return camera

    @staticmethod
    def register_runtime_camera(
        db: Session, camera_id: int, registration: CameraRuntimeRegistration
    ) -> tuple[Camera, bool]:
        """Idempotently register a camera for machine-to-machine ingestion."""
        camera = db.query(Camera).filter(Camera.id == camera_id).first()
        key_owner = (
            db.query(Camera).filter(Camera.camera_key == registration.camera_key).first()
        )
        if key_owner is not None and key_owner.id != camera_id:
            raise HTTPException(status_code=409, detail="camera_key belongs to another camera")

        created = camera is None
        if created:
            camera = Camera(id=camera_id)
            db.add(camera)
        for field_name, value in registration.model_dump().items():
            setattr(camera, field_name, value)
        camera.deleted_at = None
        if camera.status == "DELETED" or created:
            camera.status = "OFFLINE"
        try:
            db.flush()
            if created and db.bind is not None and db.bind.dialect.name == "postgresql":
                db.execute(
                    text(
                        "SELECT setval(pg_get_serial_sequence('cameras', 'id'), "
                        "COALESCE(MAX(id), 1), true) FROM cameras"
                    )
                )
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="camera registration conflict") from exc
        db.refresh(camera)
        return camera, created

    @staticmethod
    def update_camera(db: Session, camera_id: int, camera_in: CameraUpdate) -> Camera:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        for field_name, value in camera_in.model_dump(exclude_unset=True).items():
            setattr(camera, field_name, value)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail="camera_key already exists") from exc
        db.refresh(camera)
        return camera

    @staticmethod
    def delete_camera(db: Session, camera_id: int) -> None:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        camera.deleted_at = datetime.now(timezone.utc)
        camera.status = "DELETED"
        db.commit()


camera_service = CameraService()
