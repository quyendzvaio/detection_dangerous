"""Unit tests for Layer 1 without a live camera, Triton or BoxMOT."""

from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))

from ai_engine.contracts.event_schema import CapturedFrame
from ai_engine.pipeline.layer1_processor import Layer1Processor
from ai_engine.tracking.botsort_adapter import BotSortAdapter, TrackerMatch


class FakePose:
    def infer(self, frame):
        boxes = np.array([[10, 20, 50, 100]], dtype=np.float32)
        scores = np.array([0.9], dtype=np.float32)
        keypoints = np.zeros((1, 17, 3), dtype=np.float32)
        keypoints[:, :, 2] = 0.8
        return boxes, scores, keypoints


class FakeTracker:
    def update(self, detections, keypoints, frame):
        return [TrackerMatch(7, detections[0, :4], float(detections[0, 4]), 0, keypoints[0])]


def captured_frame() -> CapturedFrame:
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    return CapturedFrame(1, "cam1", 12, 1000.0, image, 160, 120)


class FakeBoxMot:
    def update(self, detections, frame):
        return np.array([[10, 20, 50, 100, 9, 0.9, 0, 1]], dtype=np.float32)


def test_botsort_adapter_uses_detection_index_for_keypoints() -> None:
    detections = np.array([[0, 0, 10, 10, 0.5, 0], [10, 20, 50, 100, 0.9, 0]], dtype=np.float32)
    keypoints = np.zeros((2, 17, 3), dtype=np.float32)
    keypoints[1, :, 0] = 42
    matches = BotSortAdapter(tracker=FakeBoxMot()).update(detections, keypoints, np.zeros((120, 160, 3), dtype=np.uint8))
    assert len(matches) == 1
    assert matches[0].native_track_id == 9
    assert matches[0].detection_index == 1
    assert np.all(matches[0].keypoints[:, 0] == 42)


def test_layer1_outputs_camera_prefixed_track_and_capture_timestamp() -> None:
    processor = Layer1Processor("cam1", FakePose(), FakeTracker())
    tracked, metrics = processor.process(captured_frame())
    assert tracked.sequence_id == 12
    assert len(tracked.persons) == 1
    person = tracked.persons[0]
    assert person.track_id == "cam1-7"
    assert person.timestamp == tracked.captured_at == 1000.0
    assert metrics.processed_frames == 1
    assert metrics.active_tracks == 1


if __name__ == "__main__":
    test_botsort_adapter_uses_detection_index_for_keypoints()
    print("PASS test_botsort_adapter_uses_detection_index_for_keypoints")
    test_layer1_outputs_camera_prefixed_track_and_capture_timestamp()
    print("PASS test_layer1_outputs_camera_prefixed_track_and_capture_timestamp")
