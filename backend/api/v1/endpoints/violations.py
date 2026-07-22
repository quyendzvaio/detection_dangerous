from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.deps import get_db
from backend.models.schemas.violation import ViolationCreate, ViolationOut, PresignedUrlOut
from backend.services.violation_service import violation_service

router = APIRouter()


@router.get("", response_model=List[ViolationOut])
def list_violations(
    camera_id: Optional[int] = Query(None, description="Lọc theo ID camera"),
    violation_type: Optional[str] = Query(None, description="Lọc theo loại vi phạm"),
    severity_level: Optional[str] = Query(None, description="Lọc theo mức độ nghiêm trọng"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Hiển thị danh sách các lỗi vi phạm an toàn lao động."""
    return violation_service.get_violations(
        db,
        camera_id=camera_id,
        violation_type=violation_type,
        severity_level=severity_level,
        skip=skip,
        limit=limit
    )


@router.post("", response_model=ViolationOut, status_code=status.HTTP_201_CREATED)
def create_violation(violation_in: ViolationCreate, db: Session = Depends(get_db)):
    """Tạo bản ghi vi phạm mới (API nội bộ/AI event)."""
    return violation_service.create_violation(db, violation_in)


@router.get("/{violation_id}", response_model=ViolationOut)
def get_violation(violation_id: int, db: Session = Depends(get_db)):
    """Xem chi tiết thông tin 1 bản ghi vi phạm."""
    violation = violation_service.get_violation_by_id(db, violation_id)
    if not violation:
        return status.HTTP_404_NOT_FOUND
    return violation


@router.get("/{violation_id}/presigned-url", response_model=PresignedUrlOut)
def get_violation_presigned_url(
    violation_id: int,
    expires_in_seconds: int = Query(3600, ge=60, le=86400),
    db: Session = Depends(get_db)
):
    """Lấy presigned URL Cloudflare R2 để xem video/ảnh bằng chứng vi phạm."""
    return violation_service.get_presigned_urls(db, violation_id, expires_in_seconds=expires_in_seconds)
