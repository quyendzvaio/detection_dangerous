from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from backend.core.deps import get_current_user, get_db
from backend.models.db.user import User
from backend.models.schemas.zone import ZoneCreate, ZoneOut, ZoneUpdate
from backend.services.zone_service import zone_service

router = APIRouter()


@router.get("", response_model=list[ZoneOut])
def list_zones(
    camera_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return zone_service.get_zones(db, current_user.tenant_id, camera_id=camera_id)


@router.post("", response_model=ZoneOut, status_code=status.HTTP_201_CREATED)
def create_zone(
    zone_in: ZoneCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return zone_service.create_zone(db, current_user.tenant_id, zone_in)


@router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone = zone_service.get_zone_by_id(db, current_user.tenant_id, zone_id)
    if zone is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone


@router.patch("/{zone_id}", response_model=ZoneOut)
@router.put("/{zone_id}", response_model=ZoneOut, include_in_schema=False)
def update_zone(
    zone_id: int,
    zone_in: ZoneUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return zone_service.update_zone(db, current_user.tenant_id, zone_id, zone_in)


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    zone_service.delete_zone(db, current_user.tenant_id, zone_id)
