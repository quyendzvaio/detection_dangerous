"""Layer 1: Pose inference + local tracking -> TrackedFrame."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from ai_engine.contracts.event_schema import CapturedFrame, TrackObservation, TrackedFrame
from ai_engine.tracking.botsort_adapter import TrackerMatch


@dataclass(frozen=True)
class Layer1MetricsSnapshot:
    processing_fps: float
    pose_ms: float
    tracker_ms: float
    end_to_end_ms: float
    active_tracks: int
    processed_frames: int


class Layer1Metrics:
    def __init__(self, window_size: int = 60) -> None:
        self._started_at = time.perf_counter()
        self._processed = 0
        self._pose_ms: deque[float] = deque(maxlen=window_size)
        self._tracker_ms: deque[float] = deque(maxlen=window_size)
        self._e2e_ms: deque[float] = deque(maxlen=window_size)

    def record(self, pose_ms: float, tracker_ms: float, end_to_end_ms: float) -> None:
        self._processed += 1
        self._pose_ms.append(pose_ms)
        self._tracker_ms.append(tracker_ms)
        self._e2e_ms.append(end_to_end_ms)

    def snapshot(self, active_tracks: int) -> Layer1MetricsSnapshot:
        elapsed = max(time.perf_counter() - self._started_at, 1e-9)
        average = lambda values: sum(values) / len(values) if values else 0.0
        return Layer1MetricsSnapshot(
            processing_fps=self._processed / elapsed,
            pose_ms=average(self._pose_ms),
            tracker_ms=average(self._tracker_ms),
            end_to_end_ms=average(self._e2e_ms),
            active_tracks=active_tracks,
            processed_frames=self._processed,
        )


class Layer1Processor:
    """Synchronous per-camera processor; Triton is shared externally by all processes."""

    def __init__(
        self,
        camera_key: str,
        pose_client: object,
        tracker: object,
        pose_model: str = "yolo_pose",
        pose_model_version: str = "unknown",
    ) -> None:
        self.camera_key = camera_key
        self.pose_client = pose_client
        self.tracker = tracker
        self.pose_model = pose_model
        self.pose_model_version = pose_model_version
        self.metrics = Layer1Metrics()

    def process(self, captured: CapturedFrame) -> tuple[TrackedFrame, Layer1MetricsSnapshot]:
        pose_started = time.perf_counter()
        boxes, scores, keypoints = self.pose_client.infer(captured.frame_bgr)
        pose_ms = (time.perf_counter() - pose_started) * 1000
        boxes = np.asarray(boxes, dtype=np.float32).reshape(-1, 4)
        scores = np.asarray(scores, dtype=np.float32).reshape(-1)
        keypoints = np.asarray(keypoints, dtype=np.float32).reshape(-1, 17, 3)
        if len(boxes) != len(scores) or len(boxes) != len(keypoints):
            raise ValueError("Pose result has inconsistent boxes, scores and keypoints")
        if len(boxes):
            classes = np.zeros((len(boxes), 1), dtype=np.float32)
            detections = np.concatenate([boxes, scores[:, None], classes], axis=1)
        else:
            detections = np.empty((0, 6), dtype=np.float32)

        tracker_started = time.perf_counter()
        matches: list[TrackerMatch] = self.tracker.update(detections, keypoints, captured.frame_bgr)
        tracker_ms = (time.perf_counter() - tracker_started) * 1000
        persons = tuple(
            TrackObservation(
                track_id=f"{captured.camera_key}-{match.native_track_id}",
                bbox_xyxy=match.bbox_xyxy,
                keypoints=match.keypoints,
                detection_confidence=match.score,
                timestamp=captured.captured_at,
            )
            for match in matches
        )
        end_to_end_ms = (time.time() - captured.captured_at) * 1000
        self.metrics.record(pose_ms, tracker_ms, end_to_end_ms)
        tracked = TrackedFrame(
            camera_id=captured.camera_id,
            camera_key=captured.camera_key,
            sequence_id=captured.sequence_id,
            captured_at=captured.captured_at,
            frame_bgr=captured.frame_bgr,
            frame_width=captured.frame_width,
            frame_height=captured.frame_height,
            persons=persons,
            pose_model=self.pose_model,
            pose_model_version=self.pose_model_version,
        )
        return tracked, self.metrics.snapshot(active_tracks=len(persons))
