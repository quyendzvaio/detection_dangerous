from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.deps import get_current_user, get_db
from backend.models.db.user import User
from backend.models.schemas.violation import (
    PresignedUrlOut,
    ViolationOut,
    ViolationStatusUpdate,
)
from backend.services.violation_service import violation_service

router = APIRouter()


@router.get("", response_model=list[ViolationOut])
def list_violations(
    camera_id: int | None = Query(None),
    violation_type: str | None = Query(None),
    severity_level: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return violation_service.get_violations(
        db,
        camera_id=camera_id,
        violation_type=violation_type,
        severity_level=severity_level,
        skip=skip,
        limit=limit,
    )


@router.get("/{violation_id}", response_model=ViolationOut)
def get_violation(violation_id: int, db: Session = Depends(get_db)):
    violation = violation_service.get_violation_by_id(db, violation_id)
    if violation is None:
        raise HTTPException(status_code=404, detail="Violation not found")
    return violation


@router.put("/{violation_id}/status", response_model=ViolationOut)
def update_violation_status(
    violation_id: int,
    body: ViolationStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return violation_service.update_status(
        db, violation_id, body.status, reviewer_id=current_user.id
    )


@router.get("/{violation_id}/presigned-url", response_model=PresignedUrlOut)
def get_violation_presigned_url(
    violation_id: int,
    expires_in_seconds: int = Query(3600, ge=60, le=86400),
    db: Session = Depends(get_db),
):
    return violation_service.get_presigned_urls(
        db, violation_id, expires_in_seconds=expires_in_seconds
    )
