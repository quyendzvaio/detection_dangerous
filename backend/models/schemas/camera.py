from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

SourceType = Literal["USB", "RTSP", "HTTP", "VIDEO_FILE"]


def infer_source_type(source: str) -> SourceType:
    normalized = source.strip().lower()
    if normalized.isdigit():
        return "USB"
    if normalized.startswith("rtsp://"):
        return "RTSP"
    if normalized.startswith(("http://", "https://")):
        return "HTTP"
    return "VIDEO_FILE"


class CameraCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    source_type: SourceType | None = None
    location_desc: str | None = Field(default=None, max_length=255)
    zone_enabled: bool = True
    fall_enabled: bool = True
    ppe_enabled: bool = False

    @model_validator(mode="after")
    def fill_source_type(self):
        if self.source_type is None:
            self.source_type = infer_source_type(self.source)
        return self


class CameraUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    camera_key: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, min_length=1, max_length=500)
    source_type: SourceType | None = None
    location_desc: str | None = Field(default=None, max_length=255)
    zone_enabled: bool | None = None
    fall_enabled: bool | None = None
    ppe_enabled: bool | None = None

    @model_validator(mode="after")
    def fill_source_type(self):
        if self.source is not None and self.source_type is None:
            self.source_type = infer_source_type(self.source)
        return self


class CameraRuntimeRegistration(BaseModel):
    """Machine-to-machine registration used by the local pipeline launcher."""

    model_config = ConfigDict(extra="forbid")

    camera_key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    source_type: SourceType | None = None
    zone_enabled: bool = True
    fall_enabled: bool = True
    ppe_enabled: bool = False

    @model_validator(mode="after")
    def fill_source_type(self):
        if self.source_type is None:
            self.source_type = infer_source_type(self.source)
        return self


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_key: str
    name: str
    source: str
    source_type: SourceType
    location_desc: str | None
    status: str
    zone_enabled: bool
    fall_enabled: bool
    ppe_enabled: bool
    config_revision: int
    applied_revision: int | None
    applied_zone_enabled: bool | None
    applied_fall_enabled: bool | None
    applied_ppe_enabled: bool | None
    config_status: Literal["PENDING", "APPLIED", "FAILED", "OFFLINE"]
    config_error: str | None
    config_applied_at: datetime | None
    last_seen_at: datetime | None
    processing_fps: float | None
    latency_ms: float | None
    last_frame_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("source")
    def redact_source_credentials(self, source: str) -> str:
        try:
            parsed = urlsplit(source)
            if parsed.username is None and parsed.password is None:
                return source
            host = parsed.hostname or ""
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
            return urlunsplit(
                (parsed.scheme, f"***:***@{host}", parsed.path, parsed.query, parsed.fragment)
            )
        except ValueError:
            return "***"


class CameraModelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_enabled: bool | None = None
    fall_enabled: bool | None = None
    ppe_enabled: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one model toggle is required")
        return self


class RuntimeZone(BaseModel):
    id: int
    name: str
    polygon: list[list[float]]


class CameraRuntimeConfig(BaseModel):
    camera_id: int
    revision: int
    zone_enabled: bool
    fall_enabled: bool
    ppe_enabled: bool
    zones: list[RuntimeZone]


class CameraRuntimeConfigAck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(gt=0)
    status: Literal["APPLIED", "FAILED"]
    zone_enabled: bool
    fall_enabled: bool
    ppe_enabled: bool
    error: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_error(self):
        if self.status == "FAILED" and not self.error:
            raise ValueError("error is required when status is FAILED")
        if self.status == "APPLIED" and self.error is not None:
            raise ValueError("error must be omitted when status is APPLIED")
        return self


class CameraTelemetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processing_fps: float = Field(ge=0, le=1000)
    latency_ms: float = Field(ge=0, le=3_600_000)
    last_frame_at: datetime


class CameraTelemetryOut(BaseModel):
    camera_id: int
    status: str
    processing_fps: float | None
    latency_ms: float | None
    last_frame_at: datetime | None
    last_seen_at: datetime | None
