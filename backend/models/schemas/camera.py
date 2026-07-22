from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class CameraCreate(BaseModel):
    name: str
    location_desc: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = "active"


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    location_desc: Optional[str] = None
    ip_address: Optional[str] = None
    status: Optional[str] = None


class CameraOut(BaseModel):
    id: int
    name: str
    location_desc: Optional[str] = None
    ip_address: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
