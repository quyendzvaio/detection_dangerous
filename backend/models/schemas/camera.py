from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CameraCreate(BaseModel):
    camera_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    location_desc: str | None = Field(default=None, max_length=255)
    status: str = "OFFLINE"
    zone_enabled: bool = True
    fall_enabled: bool = True
    ppe_enabled: bool = False


class CameraUpdate(BaseModel):
    camera_key: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, min_length=1, max_length=500)
    location_desc: str | None = Field(default=None, max_length=255)
    status: str | None = None
    zone_enabled: bool | None = None
    fall_enabled: bool | None = None
    ppe_enabled: bool | None = None


class CameraRuntimeRegistration(BaseModel):
    """Machine-to-machine registration used by the local pipeline launcher."""

    camera_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    zone_enabled: bool = True
    fall_enabled: bool = True
    ppe_enabled: bool = False


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_key: str
    name: str
    source: str
    location_desc: str | None
    status: str
    zone_enabled: bool
    fall_enabled: bool
    ppe_enabled: bool
    created_at: datetime
    updated_at: datetime
