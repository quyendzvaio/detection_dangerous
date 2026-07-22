from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session

from backend.core.deps import get_db, get_current_user
from backend.models.db.user import User
from backend.models.schemas.camera import CameraCreate, CameraUpdate, CameraOut
from backend.services.camera_service import camera_service

router = APIRouter()


@router.get("", response_model=List[CameraOut])
def list_cameras(db: Session = Depends(get_db)):
    """Lấy danh sách tất cả các camera đang hoạt động."""
    return camera_service.get_all_cameras(db)


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_camera(
    camera_in: CameraCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Thêm camera / luồng video mới vào hệ thống."""
    return camera_service.create_camera(db, camera_in)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    """Xem thông tin chi tiết của 1 camera."""
    camera = camera_service.get_camera_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return camera


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: int,
    camera_in: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cập nhật thông tin camera."""
    return camera_service.update_camera(db, camera_id, camera_in)


@router.delete("/{camera_id}", status_code=status.HTTP_200_OK)
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Xóa camera khỏi hệ thống (soft delete)."""
    camera_service.delete_camera(db, camera_id)
    return {"status": "success", "message": f"Camera {camera_id} deleted successfully"}
