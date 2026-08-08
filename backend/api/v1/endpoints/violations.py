import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.core.deps import get_current_user, get_db
from backend.models.db.user import User
from backend.models.schemas.violation import (
    PresignedUrlOut,
    ViolationOut,
)
from backend.services.violation_service import violation_service

router = APIRouter()

# Local evidence files (written by customer_sync when no Azure storage is
# configured) are served from EVIDENCE_LOCAL_DIR/{violation_id}/.
_LOCAL_EVIDENCE_DIR = Path(
    os.environ.get("EVIDENCE_LOCAL_DIR", "/data/evidence")
)


@router.get("", response_model=list[ViolationOut])
def list_violations(
    camera_id: int | None = Query(None),
    violation_type: str | None = Query(None),
    severity_level: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
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
def get_violation(
    violation_id: int,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    violation = violation_service.get_violation_by_id(db, violation_id)
    if violation is None:
        raise HTTPException(status_code=404, detail="Violation not found")
    return violation


@router.get("/{violation_id}/presigned-url", response_model=PresignedUrlOut)
def get_violation_presigned_url(
    violation_id: int,
    expires_in_seconds: int = Query(3600, ge=60, le=86400),
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    return violation_service.get_presigned_urls(
        db, violation_id, expires_in_seconds=expires_in_seconds
    )


@router.get("/{violation_id}/evidence/{kind}")
def get_local_evidence(
    violation_id: int,
    kind: str,
):
    """Serve evidence files stored locally by customer_sync (no Azure).

    Intentionally unauthenticated: the frontend renders these URLs directly
    in <img>/<video> tags (no Authorization header possible). Files live only
    on the customer host; the kind must be exactly 'image' or 'video' and the
    path is confined to EVIDENCE_LOCAL_DIR/{violation_id}/ to avoid traversal.
    """
    if kind not in {"image", "video"}:
        raise HTTPException(status_code=400, detail="kind must be image or video")
    path = _LOCAL_EVIDENCE_DIR / str(violation_id) / (
        "image.jpg" if kind == "image" else "video.mp4"
    )
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")
    media_type = "image/jpeg" if kind == "image" else "video/mp4"
    return FileResponse(path, media_type=media_type)
