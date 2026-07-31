"""Unit tests for Layer 2 dispatch without starting detector threads."""
import numpy as np

from ai_engine.contracts.event_schema import TrackObservation, TrackedFrame
from ai_engine.pipeline.layer2_runtime import (
    CameraLayer2Config,
    Layer2Control,
    Layer2Runtime,
    ModelToggles,
)


def tracked_frame():
    frame = np.zeros((100, 80, 3), dtype=np.uint8)
    person = TrackObservation(
        track_id="cam1-7",
        bbox_xyxy=np.array([10, 10, 60, 90], dtype=np.float32),
        keypoints=np.zeros((17, 3), dtype=np.float32),
        detection_confidence=0.9,
    )
    return TrackedFrame(
        camera_id=1,
        camera_key="cam1",
        captured_at=1000.0,
        frame_bgr=frame,
        frame_width=80,
        frame_height=100,
        persons=(person,),
        pose_model="yolo_pose",
        pose_model_version="1",
    )


def test_dispatch_fans_out_to_three_product_branches():
    runtime = Layer2Runtime(
        CameraLayer2Config(
            camera_id=1,
            camera_key="cam1",
            models=ModelToggles(zone=True, fall=True, ppe=True),
        )
    )
    runtime.dispatch(tracked_frame())
    metrics = runtime.metrics()
    assert metrics.dispatched == {"zone": 1, "fall": 1, "ppe": 1}
    assert metrics.queue_depths == {"zone": 1, "fall": 1, "ppe": 1}
    assert "reid" not in metrics.dispatched


def test_reid_is_not_an_accepted_model_toggle():
    control = Layer2Control(ModelToggles())
    try:
        control.set_models(reid=True)
        raise AssertionError("ReID toggle should not be accepted in this phase")
    except ValueError:
        pass
