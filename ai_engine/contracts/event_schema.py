"""Internal, in-memory contracts shared by AI pipeline layers."""

from dataclasses import dataclass

import numpy as np

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class CapturedFrame:
    """One raw BGR frame emitted by Layer 0 before inference or tracking."""

    camera_id: int
    camera_key: str
    sequence_id: int
    captured_at: float
    frame_bgr: np.ndarray
    frame_width: int
    frame_height: int


@dataclass(frozen=True)
class TrackObservation:
    """One tracked person in a frame after Layer 1 pose and tracking."""

    track_id: str
    bbox_xyxy: np.ndarray
    keypoints: np.ndarray
    detection_confidence: float
    timestamp: float


@dataclass(frozen=True)
class TrackedFrame:
    """Layer 1 output: one frame plus all tracked people in it."""

    camera_id: int
    camera_key: str
    sequence_id: int
    captured_at: float
    frame_bgr: np.ndarray
    frame_width: int
    frame_height: int
    persons: tuple[TrackObservation, ...]
    pose_model: str
    pose_model_version: str


__all__ = [
    "SCHEMA_VERSION",
    "CapturedFrame",
    "TrackObservation",
    "TrackedFrame",
]
