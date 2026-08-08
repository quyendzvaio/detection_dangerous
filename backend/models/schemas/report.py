from typing import List, Dict
from pydantic import BaseModel


class ViolationTypeSummary(BaseModel):
    violation_type: str
    count: int


class CameraViolationSummary(BaseModel):
    camera_id: int
    camera_name: str
    count: int


class ReportSummaryOut(BaseModel):
    total_violations: int
    total_cameras: int
    total_users: int
    violations_by_type: List[ViolationTypeSummary]
    violations_by_camera: List[CameraViolationSummary]
