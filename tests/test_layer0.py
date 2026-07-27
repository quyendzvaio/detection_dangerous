"""Tests for the Layer 0 latest-frame policy."""

from pathlib import Path
import sys

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))

from ai_engine.contracts.event_schema import CapturedFrame
from ai_engine.ingest.latest_frame import LatestFrameBuffer
from ai_engine.ingest.layer0_multi_runner import parse_camera_spec


def frame(sequence_id: int) -> CapturedFrame:
    image = np.zeros((2, 3, 3), dtype=np.uint8)
    return CapturedFrame(
        camera_id=1,
        camera_key="cam1",
        sequence_id=sequence_id,
        captured_at=1000.0 + sequence_id,
        frame_bgr=image,
        frame_width=3,
        frame_height=2,
    )


def test_latest_frame_replaces_unread_frame() -> None:
    buffer = LatestFrameBuffer()
    buffer.publish(frame(1))
    buffer.publish(frame(2))
    received = buffer.take_latest(timeout=0)
    assert received is not None
    assert received.sequence_id == 2
    stats = buffer.stats()
    assert stats.accepted == 2
    assert stats.overwritten == 1
    assert stats.delivered == 1


def test_camera_spec_preserves_rtsp_colons() -> None:
    config = parse_camera_spec("2:cam2:rtsp://127.0.0.1:8554/stream")
    assert config.camera_id == 2
    assert config.camera_key == "cam2"
    assert config.source == "rtsp://127.0.0.1:8554/stream"


def test_closed_buffer_wakes_waiter() -> None:
    buffer = LatestFrameBuffer()
    buffer.close()
    assert buffer.take_latest(timeout=0) is None


def test_frame_contract_keeps_capture_metadata() -> None:
    captured = frame(7)
    assert captured.camera_key == "cam1"
    assert captured.sequence_id == 7
    assert captured.frame_bgr.shape == (2, 3, 3)


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
