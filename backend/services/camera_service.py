from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.db.camera import Camera
from backend.models.db.zone import Zone
from backend.models.schemas.camera import (
    CameraCreate,
    CameraRuntimeConfig,
    CameraRuntimeConfigAck,
    CameraRuntimeRegistration,
    CameraTelemetryIn,
    CameraTelemetryOut,
    CameraUpdate,
    RuntimeZone,
)


class CameraService:
    CONFIG_FIELDS = frozenset(
        {"source", "source_type", "zone_enabled", "fall_enabled", "ppe_enabled"}
    )

    @staticmethod
    def mark_config_pending(camera: Camera) -> None:
        camera.config_revision = (camera.config_revision or 0) + 1
        camera.config_status = "PENDING" if camera.status == "ONLINE" else "OFFLINE"
        camera.config_error = None

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
        camera.status = "OFFLINE"
        camera.config_status = "OFFLINE"
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
        registration_data = registration.model_dump()
        if not created:
            for field_name in ("zone_enabled", "fall_enabled", "ppe_enabled"):
                registration_data.pop(field_name, None)
        for field_name, value in registration_data.items():
            setattr(camera, field_name, value)
        camera.deleted_at = None
        if camera.status == "DELETED" or created:
            camera.status = "OFFLINE"
        if created:
            camera.config_status = "OFFLINE"
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
        changes = camera_in.model_dump(exclude_unset=True)
        config_changed = any(
            field_name in CameraService.CONFIG_FIELDS
            and getattr(camera, field_name) != value
            for field_name, value in changes.items()
        )
        for field_name, value in changes.items():
            setattr(camera, field_name, value)
        if config_changed:
            CameraService.mark_config_pending(camera)
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
        camera.config_status = "OFFLINE"
        db.commit()

    @staticmethod
    def get_runtime_config(db: Session, camera_id: int) -> CameraRuntimeConfig:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        zones = (
            db.query(Zone)
            .filter(
                Zone.camera_id == camera_id,
                Zone.deleted_at.is_(None),
                Zone.is_active.is_(True),
            )
            .order_by(Zone.id)
            .all()
        )
        return CameraRuntimeConfig(
            camera_id=camera.id,
            revision=camera.config_revision,
            zone_enabled=camera.zone_enabled,
            fall_enabled=camera.fall_enabled,
            ppe_enabled=camera.ppe_enabled,
            zones=[
                RuntimeZone(id=zone.id, name=zone.name, polygon=zone.polygon_json)
                for zone in zones
            ],
        )

    @staticmethod
    def acknowledge_runtime_config(
        db: Session, camera_id: int, ack: CameraRuntimeConfigAck
    ) -> Camera:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        if ack.revision > camera.config_revision:
            raise HTTPException(status_code=409, detail="Revision is newer than desired config")
        if ack.revision < camera.config_revision:
            raise HTTPException(status_code=409, detail="Stale config acknowledgement")

        camera.applied_revision = ack.revision
        camera.applied_zone_enabled = ack.zone_enabled
        camera.applied_fall_enabled = ack.fall_enabled
        camera.applied_ppe_enabled = ack.ppe_enabled
        camera.config_status = ack.status
        camera.config_error = ack.error
        camera.config_applied_at = datetime.now(timezone.utc)
        camera.last_seen_at = camera.config_applied_at
        camera.status = "ONLINE"
        db.commit()
        db.refresh(camera)
        return camera

    @staticmethod
    def update_telemetry(
        db: Session, camera_id: int, telemetry: CameraTelemetryIn
    ) -> CameraTelemetryOut:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        now = datetime.now(timezone.utc)
        camera.processing_fps = telemetry.processing_fps
        camera.latency_ms = telemetry.latency_ms
        camera.last_frame_at = telemetry.last_frame_at
        camera.last_seen_at = now
        camera.status = "ONLINE"
        db.commit()
        return CameraService.telemetry(camera)

    @staticmethod
    def telemetry(camera: Camera) -> CameraTelemetryOut:
        return CameraTelemetryOut(
            camera_id=camera.id,
            status=camera.status,
            processing_fps=camera.processing_fps,
            latency_ms=camera.latency_ms,
            last_frame_at=camera.last_frame_at,
            last_seen_at=camera.last_seen_at,
        )


camera_service = CameraService()
