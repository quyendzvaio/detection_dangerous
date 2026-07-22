from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from backend.models.db.camera import Camera
from backend.models.schemas.camera import CameraCreate, CameraUpdate


class CameraService:
    @staticmethod
    def get_all_cameras(db: Session, include_deleted: bool = False) -> List[Camera]:
        query = db.query(Camera)
        if not include_deleted:
            query = query.filter(Camera.deleted_at.is_(None))
        return query.all()

    @staticmethod
    def get_camera_by_id(db: Session, camera_id: int) -> Optional[Camera]:
        return db.query(Camera).filter(Camera.id == camera_id, Camera.deleted_at.is_(None)).first()

    @staticmethod
    def create_camera(db: Session, camera_in: CameraCreate) -> Camera:
        camera = Camera(
            name=camera_in.name,
            location_desc=camera_in.location_desc,
            ip_address=camera_in.ip_address,
            status=camera_in.status or "active"
        )
        db.add(camera)
        db.commit()
        db.refresh(camera)
        return camera

    @staticmethod
    def update_camera(db: Session, camera_id: int, camera_in: CameraUpdate) -> Camera:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if not camera:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
        
        if camera_in.name is not None:
            camera.name = camera_in.name
        if camera_in.location_desc is not None:
            camera.location_desc = camera_in.location_desc
        if camera_in.ip_address is not None:
            camera.ip_address = camera_in.ip_address
        if camera_in.status is not None:
            camera.status = camera_in.status

        db.commit()
        db.refresh(camera)
        return camera

    @staticmethod
    def delete_camera(db: Session, camera_id: int, soft_delete: bool = True) -> bool:
        camera = CameraService.get_camera_by_id(db, camera_id)
        if not camera:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
        
        if soft_delete:
            camera.deleted_at = datetime.now(timezone.utc)
            camera.status = "deleted"
        else:
            db.delete(camera)
        
        db.commit()
        return True


camera_service = CameraService()
