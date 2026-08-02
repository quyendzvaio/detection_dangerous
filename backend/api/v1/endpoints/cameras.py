from typing import List
from fastapi import APIRouter, Depends, status, HTTPException, Response
from sqlalchemy.orm import Session

from backend.core.deps import get_db, get_current_user
from backend.models.db.user import User
from backend.models.schemas.camera import (
    CameraCreate,
    CameraModelUpdate,
    CameraUpdate,
    CameraOut,
    CameraTelemetryOut,
)
from backend.services.camera_service import camera_service
from backend.frame_store import latest_frames

router = APIRouter()


@router.get("", response_model=List[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
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
def get_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Xem thông tin chi tiết của 1 camera."""
    camera = camera_service.get_camera_by_id(db, camera_id)
    if not camera:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return camera


@router.patch("/{camera_id}", response_model=CameraOut)
@router.put("/{camera_id}", response_model=CameraOut, include_in_schema=False)
def update_camera(
    camera_id: int,
    camera_in: CameraUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Cập nhật thông tin camera."""
    return camera_service.update_camera(db, camera_id, camera_in)


@router.patch("/{camera_id}/models", response_model=CameraOut)
def update_camera_models(
    camera_id: int,
    model_in: CameraModelUpdate,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    return camera_service.update_camera(
        db, camera_id, CameraUpdate(**model_in.model_dump(exclude_unset=True))
    )


@router.get("/{camera_id}/telemetry", response_model=CameraTelemetryOut)
def get_camera_telemetry(
    camera_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    camera = camera_service.get_camera_by_id(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return camera_service.telemetry(camera)


@router.get("/{camera_id}/stream", response_class=Response)
def get_latest_camera_frame(
    camera_id: int,
    overlay: bool = True,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    if camera_service.get_camera_by_id(db, camera_id) is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    jpeg = latest_frames.get(camera_id, overlay)
    if jpeg is None:
        raise HTTPException(status_code=503, detail="Camera frame is not available")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.delete("/{camera_id}", status_code=status.HTTP_200_OK)
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Xóa camera khỏi hệ thống (soft delete)."""
    camera_service.delete_camera(db, camera_id)
    return {"status": "success", "message": f"Camera {camera_id} deleted successfully"}
