from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SafetyEventBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    camera_id: int = Field(gt=0)
    track_id: str = Field(min_length=1, max_length=150)
    detected_time: datetime
    evidence_status: Literal["PROCESSING", "READY", "FAILED"] = "PROCESSING"
    image_storage_key: str | None = Field(default=None, max_length=1024)
    video_storage_key: str | None = Field(default=None, max_length=1024)


class PPEViolationRequest(SafetyEventBase):
    violation_type: Literal["PPE_VIOLATION"]
    severity_level: Literal["DANGER"]
    violation_codes: list[
        Literal["NO_HELMET", "NO_GLASSES", "NO_GLOVES", "NO_VEST"]
    ] = Field(min_length=1)

    @field_validator("violation_codes")
    @classmethod
    def codes_must_be_unique(cls, codes: list[str]) -> list[str]:
        if len(set(codes)) != len(codes):
            raise ValueError("violation_codes must be unique")
        return codes


class FallDetectedRequest(SafetyEventBase):
    violation_type: Literal["FALL_DETECTED"]
    severity_level: Literal["CRITICAL"]
    confidence: float = Field(ge=0.0, le=1.0)


class FallSuspectedRequest(SafetyEventBase):
    violation_type: Literal["FALL_SUSPECTED"]
    severity_level: Literal["WARNING"]
    confidence: float = Field(ge=0.0, le=1.0)


class RestrictedZoneRequest(SafetyEventBase):
    violation_type: Literal["RESTRICTED_ZONE"]
    severity_level: Literal["DANGER"]
    zone_id: int = Field(gt=0)


SafetyEventRequest = Annotated[
    Union[
        PPEViolationRequest,
        FallDetectedRequest,
        FallSuspectedRequest,
        RestrictedZoneRequest,
    ],
    Field(discriminator="violation_type"),
]


class CameraStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_category: Literal["CAMERA_STATUS"]
    camera_id: int = Field(gt=0)
    status: Literal["ONLINE", "OFFLINE"]
    observed_time: datetime
    reason: str | None = Field(default=None, max_length=500)
    source: str = Field(default="SUPERVISOR", min_length=1, max_length=100)


class EventIngestResponse(BaseModel):
    status: Literal["created", "duplicate"]
    event_id: UUID
    record_id: int
