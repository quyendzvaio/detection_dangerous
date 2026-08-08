from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.db.camera import Camera
from backend.models.db.zone import Zone
from backend.models.schemas.zone import ZoneCreate, ZoneUpdate


class ZoneService:
    @staticmethod
    def get_zones(db: Session, tenant_id: int, camera_id: int | None = None) -> list[Zone]:
        query = db.query(Zone).filter(Zone.deleted_at.is_(None), Zone.tenant_id == tenant_id)
        if camera_id is not None:
            query = query.filter(Zone.camera_id == camera_id)
        return query.order_by(Zone.id).all()

    @staticmethod
    def get_zone_by_id(db: Session, tenant_id: int, zone_id: int) -> Zone | None:
        return (
            db.query(Zone)
            .filter(
                Zone.id == zone_id,
                Zone.tenant_id == tenant_id,
                Zone.deleted_at.is_(None),
            )
            .first()
        )

    @staticmethod
    def _mark_camera_config_pending(camera: Camera) -> None:
        camera.config_revision = (camera.config_revision or 0) + 1
        camera.config_status = "PENDING" if camera.status == "ONLINE" else "OFFLINE"
        camera.config_error = None

    @staticmethod
    def create_zone(db: Session, tenant_id: int, zone_in: ZoneCreate) -> Zone:
        camera = (
            db.query(Camera)
            .filter(
                Camera.id == zone_in.camera_id,
                Camera.tenant_id == tenant_id,
                Camera.deleted_at.is_(None),
            )
            .first()
        )
        if camera is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        zone = Zone(**zone_in.model_dump())
        zone.tenant_id = tenant_id
        db.add(zone)
        ZoneService._mark_camera_config_pending(camera)
        db.commit()
        db.refresh(zone)
        return zone

    @staticmethod
    def update_zone(db: Session, tenant_id: int, zone_id: int, zone_in: ZoneUpdate) -> Zone:
        zone = ZoneService.get_zone_by_id(db, tenant_id, zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found")
        for field_name, value in zone_in.model_dump(exclude_unset=True).items():
            setattr(zone, field_name, value)
        ZoneService._mark_camera_config_pending(zone.camera)
        db.commit()
        db.refresh(zone)
        return zone

    @staticmethod
    def delete_zone(db: Session, tenant_id: int, zone_id: int) -> None:
        zone = ZoneService.get_zone_by_id(db, tenant_id, zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found")
        zone.deleted_at = datetime.now(timezone.utc)
        zone.is_active = False
        ZoneService._mark_camera_config_pending(zone.camera)
        db.commit()


zone_service = ZoneService()
