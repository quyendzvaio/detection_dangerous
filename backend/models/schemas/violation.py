from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ViolationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: UUID
    camera_id: int
    track_id: str
    detected_time: datetime
    violation_type: str
    severity_level: str
    confidence: float | None
    zone_id: int | None
    violation_codes: list[str] | None
    evidence_status: str
    image_storage_key: str | None
    video_storage_key: str | None
    status: str
    reviewed_by: int | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ViolationStatusUpdate(BaseModel):
    status: Literal["REVIEWED", "DISMISSED", "RESOLVED"]


class PresignedUrlOut(BaseModel):
    violation_id: int
    video_url: str | None = None
    image_url: str | None = None
    expires_in_seconds: int = 3600
