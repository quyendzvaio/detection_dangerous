"""Authoritative contracts exchanged inside the AI pipeline and with backend."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar, TypeAlias

import numpy as np


# Internal, in-memory messages. Arrays are never serialized to backend.
@dataclass(frozen=True)
class CapturedFrame:
    """Layer 0 output: the freshest decoded BGR frame from one camera."""

    camera_id: int
    camera_key: str
    captured_at: float
    frame_bgr: np.ndarray
    frame_width: int
    frame_height: int


@dataclass(frozen=True)
class TrackObservation:
    """One person observed by pose detection and tracking in a TrackedFrame."""

    track_id: str
    bbox_xyxy: np.ndarray
    keypoints: np.ndarray
    detection_confidence: float


@dataclass(frozen=True)
class TrackedFrame:
    """Layer 1 output: one frame plus every tracked person in that frame."""

    camera_id: int
    camera_key: str
    captured_at: float
    frame_bgr: np.ndarray
    frame_width: int
    frame_height: int
    persons: tuple[TrackObservation, ...]
    pose_model: str
    pose_model_version: str


@dataclass(frozen=True)
class FallTask:
    """Minimal Layer 1 -> fall branch message."""

    camera_id: int
    camera_key: str
    track_id: str
    keypoints: np.ndarray
    captured_at: float


@dataclass(frozen=True)
class ZoneTask:
    """Minimal Layer 1 -> restricted-zone branch message."""

    camera_id: int
    camera_key: str
    track_id: str
    bbox_xyxy: np.ndarray
    captured_at: float
    frame_width: int
    frame_height: int


@dataclass(frozen=True)
class PpeTask:
    """Owned crop and crop-relative keypoints for PPE analysis."""

    camera_id: int
    camera_key: str
    track_id: str
    person_crop_bgr: np.ndarray
    relative_keypoints: np.ndarray
    captured_at: float


# External events. These are JSON-safe contracts sent to backend.
class ViolationType(str, Enum):
    PPE_VIOLATION = "PPE_VIOLATION"
    FALL_DETECTED = "FALL_DETECTED"
    FALL_SUSPECTED = "FALL_SUSPECTED"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"


class Severity(str, Enum):
    WARNING = "WARNING"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"


class PpeViolationCode(str, Enum):
    NO_HELMET = "NO_HELMET"
    NO_GLASSES = "NO_GLASSES"
    NO_GLOVES = "NO_GLOVES"
    NO_VEST = "NO_VEST"


class EvidenceStatus(str, Enum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass(frozen=True, kw_only=True)
class SafetyEvent:
    """Common immutable fields for every persisted safety event."""

    camera_id: int
    track_id: str
    detected_at: float
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    image_storage_key: str | None = None
    video_storage_key: str | None = None
    evidence_status: EvidenceStatus = EvidenceStatus.PROCESSING

    violation_type: ClassVar[ViolationType]
    severity: ClassVar[Severity]

    def __post_init__(self) -> None:
        if self.camera_id <= 0:
            raise ValueError("camera_id must be positive")
        if not self.track_id:
            raise ValueError("track_id must not be empty")
        uuid.UUID(self.event_id)

    @property
    def iso_detected_time(self) -> str:
        return datetime.fromtimestamp(self.detected_at, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        )

    def to_backend_payload(self) -> dict[str, object]:
        """Serialize the stable Layer 2 -> backend JSON contract."""
        return {
            "event_id": self.event_id,
            "camera_id": self.camera_id,
            "track_id": self.track_id,
            "violation_type": self.violation_type.value,
            "severity_level": self.severity.value,
            "detected_time": self.iso_detected_time,
            "evidence_status": self.evidence_status.value,
            "image_storage_key": self.image_storage_key,
            "video_storage_key": self.video_storage_key,
        }


@dataclass(frozen=True, kw_only=True)
class PPEViolationEvent(SafetyEvent):
    violation_codes: tuple[PpeViolationCode, ...]

    violation_type: ClassVar[ViolationType] = ViolationType.PPE_VIOLATION
    severity: ClassVar[Severity] = Severity.DANGER

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.violation_codes:
            raise ValueError("PPEViolationEvent requires at least one violation code")
        if len(set(self.violation_codes)) != len(self.violation_codes):
            raise ValueError("violation_codes must be unique")

    def to_backend_payload(self) -> dict[str, object]:
        payload = super().to_backend_payload()
        payload["violation_codes"] = [code.value for code in self.violation_codes]
        return payload


@dataclass(frozen=True, kw_only=True)
class FallDetectedEvent(SafetyEvent):
    confidence: float

    violation_type: ClassVar[ViolationType] = ViolationType.FALL_DETECTED
    severity: ClassVar[Severity] = Severity.CRITICAL

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_confidence(self.confidence)

    def to_backend_payload(self) -> dict[str, object]:
        payload = super().to_backend_payload()
        payload["confidence"] = self.confidence
        return payload


@dataclass(frozen=True, kw_only=True)
class FallSuspectedEvent(SafetyEvent):
    """Initial fall incident warning before persistent-down confirmation."""

    confidence: float

    violation_type: ClassVar[ViolationType] = ViolationType.FALL_SUSPECTED
    severity: ClassVar[Severity] = Severity.WARNING

    def __post_init__(self) -> None:
        super().__post_init__()
        _validate_confidence(self.confidence)

    def to_backend_payload(self) -> dict[str, object]:
        payload = super().to_backend_payload()
        payload["confidence"] = self.confidence
        return payload


@dataclass(frozen=True, kw_only=True)
class RestrictedZoneEvent(SafetyEvent):
    zone_id: int

    violation_type: ClassVar[ViolationType] = ViolationType.RESTRICTED_ZONE
    severity: ClassVar[Severity] = Severity.DANGER

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.zone_id <= 0:
            raise ValueError("zone_id must be positive")

    def to_backend_payload(self) -> dict[str, object]:
        payload = super().to_backend_payload()
        payload["zone_id"] = self.zone_id
        return payload


class CameraStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


@dataclass(frozen=True, kw_only=True)
class CameraStatusEvent:
    """Operational event; intentionally separate from safety violations."""

    camera_id: int
    status: CameraStatus
    observed_at: float
    reason: str | None = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str = "SUPERVISOR"

    def __post_init__(self) -> None:
        if self.camera_id <= 0:
            raise ValueError("camera_id must be positive")
        uuid.UUID(self.event_id)

    def to_backend_payload(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "event_category": "CAMERA_STATUS",
            "camera_id": self.camera_id,
            "status": self.status.value,
            "observed_time": datetime.fromtimestamp(
                self.observed_at, tz=timezone.utc
            ).isoformat(timespec="milliseconds"),
            "reason": self.reason,
            "source": self.source,
        }


def _validate_confidence(value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError("confidence must be in [0, 1]")


DomainEvent: TypeAlias = SafetyEvent | CameraStatusEvent

__all__ = [
    "CapturedFrame",
    "TrackObservation",
    "TrackedFrame",
    "FallTask",
    "ZoneTask",
    "PpeTask",
    "ViolationType",
    "Severity",
    "PpeViolationCode",
    "EvidenceStatus",
    "SafetyEvent",
    "PPEViolationEvent",
    "FallDetectedEvent",
    "FallSuspectedEvent",
    "RestrictedZoneEvent",
    "CameraStatus",
    "CameraStatusEvent",
    "DomainEvent",
]
