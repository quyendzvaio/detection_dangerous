from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.db.camera import Camera
from backend.models.db.zone import Zone
from backend.models.schemas.zone import ZoneCreate, ZoneUpdate


class ZoneService:
    @staticmethod
    def get_zones(db: Session, camera_id: int | None = None) -> list[Zone]:
        query = db.query(Zone)
        if camera_id is not None:
            query = query.filter(Zone.camera_id == camera_id)
        return query.order_by(Zone.id).all()

    @staticmethod
    def get_zone_by_id(db: Session, zone_id: int) -> Zone | None:
        return db.query(Zone).filter(Zone.id == zone_id).first()

    @staticmethod
    def create_zone(db: Session, zone_in: ZoneCreate) -> Zone:
        if db.query(Camera.id).filter(Camera.id == zone_in.camera_id).first() is None:
            raise HTTPException(status_code=404, detail="Camera not found")
        zone = Zone(**zone_in.model_dump())
        db.add(zone)
        db.commit()
        db.refresh(zone)
        return zone

    @staticmethod
    def update_zone(db: Session, zone_id: int, zone_in: ZoneUpdate) -> Zone:
        zone = ZoneService.get_zone_by_id(db, zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found")
        for field_name, value in zone_in.model_dump(exclude_unset=True).items():
            setattr(zone, field_name, value)
        db.commit()
        db.refresh(zone)
        return zone

    @staticmethod
    def delete_zone(db: Session, zone_id: int) -> None:
        zone = ZoneService.get_zone_by_id(db, zone_id)
        if zone is None:
            raise HTTPException(status_code=404, detail="Zone not found")
        db.delete(zone)
        db.commit()


zone_service = ZoneService()
