from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

EvidenceKind = Literal["IMAGE", "VIDEO"]
EvidenceContentType = Literal["image/jpeg", "video/mp4"]


class EvidenceUploadSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EvidenceKind
    content_type: EvidenceContentType
    size_bytes: int = Field(gt=0, le=250 * 1024 * 1024)

    @model_validator(mode="after")
    def kind_matches_content_type(self):
        expected = "image/jpeg" if self.kind == "IMAGE" else "video/mp4"
        if self.content_type != expected:
            raise ValueError(f"{self.kind} evidence requires {expected}")
        return self


class EvidencePresignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objects: list[EvidenceUploadSpec] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def kinds_are_unique(self):
        kinds = [item.kind for item in self.objects]
        if len(kinds) != len(set(kinds)):
            raise ValueError("evidence kinds must be unique per request")
        return self


class EvidenceUploadOut(BaseModel):
    evidence_id: int
    kind: EvidenceKind
    object_key: str
    upload_url: str
    upload_headers: dict[str, str]
    content_type: EvidenceContentType
    expires_in_seconds: int


class EvidencePresignResponse(BaseModel):
    event_id: UUID
    uploads: list[EvidenceUploadOut]


class EvidenceCompleteItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: int = Field(gt=0)
    size_bytes: int = Field(gt=0, le=250 * 1024 * 1024)
    etag: str | None = Field(default=None, max_length=255)


class EvidenceCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objects: list[EvidenceCompleteItem] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def ids_are_unique(self):
        ids = [item.evidence_id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        return self


class EvidenceFailItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=1000)


class EvidenceFailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objects: list[EvidenceFailItem] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def ids_are_unique(self):
        ids = [item.evidence_id for item in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        return self


class EvidenceObjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: EvidenceKind
    object_key: str
    status: Literal["PROCESSING", "READY", "FAILED"]
    content_type: EvidenceContentType
    size_bytes: int | None
    etag: str | None
    failure_reason: str | None
    upload_expires_at: datetime | None
    uploaded_at: datetime | None


class EvidenceLifecycleResponse(BaseModel):
    event_id: UUID
    evidence_status: Literal["PROCESSING", "READY", "FAILED"]
    image_storage_key: str | None
    video_storage_key: str | None
    objects: list[EvidenceObjectOut]
