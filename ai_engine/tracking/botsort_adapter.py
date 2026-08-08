"""Adapter isolating BoxMOT output details from the rest of Layer 1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class TrackerMatch:
    native_track_id: int
    bbox_xyxy: np.ndarray
    score: float
    detection_index: int
    keypoints: np.ndarray


def _iou(one: np.ndarray, many: np.ndarray) -> np.ndarray:
    x1 = np.maximum(one[0], many[:, 0])
    y1 = np.maximum(one[1], many[:, 1])
    x2 = np.minimum(one[2], many[:, 2])
    y2 = np.minimum(one[3], many[:, 3])
    inter = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    area_one = max(0.0, (one[2] - one[0]) * (one[3] - one[1]))
    area_many = np.maximum(0.0, many[:, 2] - many[:, 0]) * np.maximum(0.0, many[:, 3] - many[:, 1])
    return inter / (area_one + area_many - inter + 1e-9)


class BotSortAdapter:
    """Map BoxMOT tracks back to the Pose detection/keypoint that produced them."""

    def __init__(self, frame_rate: int = 25, tracker: Optional[object] = None) -> None:
        if tracker is None:
            from boxmot.trackers.bbox.botsort import BotSort
            tracker = BotSort(with_reid=False, use_cmc=False, frame_rate=frame_rate)
        self._tracker = tracker

    def update(self, detections: np.ndarray, keypoints: np.ndarray, frame_bgr: np.ndarray) -> list[TrackerMatch]:
        """Return tracker matches; prefer BoxMOT det_index, fall back to IoU mapping."""
        detections = np.asarray(detections, dtype=np.float32).reshape(-1, 6)
        keypoints = np.asarray(keypoints, dtype=np.float32).reshape(-1, 17, 3)
        tracks = np.asarray(self._tracker.update(detections, frame_bgr))
        if tracks.size == 0:
            return []
        tracks = tracks.reshape(1, -1) if tracks.ndim == 1 else tracks
        matches = []
        used_indices: set[int] = set()
        for row in tracks:
            bbox = np.asarray(row[:4], dtype=np.float32)
            det_index = self._resolve_detection_index(row, bbox, detections, used_indices)
            if det_index is None:
                continue
            used_indices.add(det_index)
            score = float(detections[det_index, 4])
            matches.append(TrackerMatch(
                native_track_id=int(row[4]),
                bbox_xyxy=bbox,
                score=score,
                detection_index=det_index,
                keypoints=keypoints[det_index],
            ))
        return matches

    @staticmethod
    def _resolve_detection_index(
        row: np.ndarray,
        bbox: np.ndarray,
        detections: np.ndarray,
        used_indices: set[int],
    ) -> Optional[int]:
        if len(row) >= 8:
            candidate = int(row[7])
            if 0 <= candidate < len(detections) and candidate not in used_indices:
                return candidate
        if len(detections) == 0:
            return None
        scores = _iou(bbox, detections[:, :4])
        for index in np.argsort(scores)[::-1]:
            if int(index) not in used_indices:
                return int(index)
        return None
