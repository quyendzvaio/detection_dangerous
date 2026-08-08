from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=150)


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_key: str
    name: str
    is_active: bool


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    credential_label: str = Field(default="default", min_length=1, max_length=100)


class DeviceCredentialOut(BaseModel):
    device_id: int
    tenant_id: int
    device_key: str
    credential: str


class DeviceStatusOut(BaseModel):
    device_id: int
    tenant_id: int
    status: Literal["ONLINE", "OFFLINE"]
    last_seen_at: datetime | None


class StreamCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_key: str = Field(min_length=1, max_length=100)
    path: str = Field(min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_./{}-]+$")
    protocol: Literal["RTSP"] = "RTSP"


class StreamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tenant_id: int
    device_id: int
    camera_key: str
    path: str
    protocol: str
    status: str


class DeviceConfigOut(BaseModel):
    device_id: int
    tenant_id: int
    streams: list[StreamOut]


class CameraProfileCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    model_toggles: dict[str, bool] = Field(
        default_factory=lambda: {"zone": True, "fall": True, "ppe": False}
    )
    operational_config: dict[str, object] = Field(default_factory=dict)


class CameraProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    name: str
    revision: int
    model_toggles: dict[str, bool]
    operational_config: dict[str, object]


class ModelAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: int = Field(gt=0)
    model_name: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=100)


class ModelAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    profile_id: int
    model_name: str
    model_version: str
    is_active: bool
