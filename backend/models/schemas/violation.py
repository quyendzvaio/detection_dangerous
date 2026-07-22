from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel


class ViolationCreate(BaseModel):
    camera_id: int
    violation_type: str
    severity_level: Optional[str] = "WARNING"
    worker_code: Optional[str] = None
    video_bucket: Optional[str] = None
    video_path: Optional[str] = None
    image_path: Optional[str] = None
    ai_metadata: Optional[Dict[str, Any]] = None


class ViolationOut(BaseModel):
    id: int
    camera_id: int
    detected_time: datetime
    violation_type: str
    severity_level: str
    worker_code: Optional[str] = None
    video_bucket: Optional[str] = None
    video_path: Optional[str] = None
    image_path: Optional[str] = None
    status: str
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    ai_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PresignedUrlOut(BaseModel):
    violation_id: int
    video_url: Optional[str] = None
    image_url: Optional[str] = None
    expires_in_seconds: int = 3600
