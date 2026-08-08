"""
Guard tests: the fall preprocessing in ai_engine.analytics.fall must keep
producing exactly what the training notebook produced. Run directly:

    python3 tests/test_fall_preprocessing.py
"""
import sys
from pathlib import Path

import numpy as np

sys.path.append(str(Path(__file__).resolve().parent.parent))

from ai_engine.analytics.fall import (  # noqa: E402
    KP, FallConfig, FallDecision, FallPreprocessor, FallProcessor,
    HeuristicFallDetector,
    TrackKeypointBuffer, add_motion_features, interpolate_missing,
    normalize_pose_frame, resample_sequence, resample_sequence_at_timestamps,
)
from ai_engine.contracts.event_schema import FallTask  # noqa: E402

CONFIG_PATH = Path(__file__).resolve().parent.parent / 'weights/fall_model/inference_config.json'
MIN_CONF = 0.2


def make_upright_pose(cx=100.0, cy=100.0, torso=50.0, conf=0.9):
    """Synthetic standing person: shoulders `torso` px above hips."""
    pose = np.zeros((17, 3), dtype=np.float32)
    pose[:, 0] = cx
    pose[:, 1] = cy
    pose[:, 2] = conf
    pose[KP['left_shoulder']] = [cx - 20, cy - torso, conf]
    pose[KP['right_shoulder']] = [cx + 20, cy - torso, conf]
    pose[KP['left_hip']] = [cx - 15, cy, conf]
    pose[KP['right_hip']] = [cx + 15, cy, conf]
    return pose


def make_fallen_pose(conf=0.9):
    pose = make_upright_pose(conf=conf)
    pose[KP['left_shoulder']] = [150, 100, conf]
    pose[KP['right_shoulder']] = [155, 105, conf]
    return pose


class FakeDetector:
    def __init__(self, probability=0.9):
        self.probability = probability

    def predict(self, features):
        return self.probability


def fall_task(timestamp, pose=None):
    keypoints = make_fallen_pose() if pose is None else pose
    return FallTask(1, 'cam1', 'cam1-7', keypoints, timestamp)


def make_processor():
    config = FallConfig(
        max_frames=60,
        num_features=85,
        min_keypoint_confidence=0.2,
        threshold=0.5,
        window_seconds=1.0,
        min_real_points=3,
        still_down_confirmation_seconds=5.0,
        recovery_confirmation_seconds=2.0,
    )
    decision = FallDecision(threshold=0.5, m=1, n=1, cooldown_seconds=30.0)
    return FallProcessor(
        config, FakeDetector(), decision=decision, inference_interval_s=0.0
    )


def test_normalize_centers_on_hip_and_scales_by_torso():
    pose = make_upright_pose()
    flat = normalize_pose_frame(pose, MIN_CONF)
    out = flat.reshape(17, 3)
    hip_mid = (out[KP['left_hip'], :2] + out[KP['right_hip'], :2]) / 2
    assert np.allclose(hip_mid, [0, 0], atol=1e-5), f'hip mid not at origin: {hip_mid}'
    shoulder_mid = (out[KP['left_shoulder'], :2] + out[KP['right_shoulder'], :2]) / 2
    # torso length (hip mid -> shoulder mid) must normalize to exactly 1
    assert np.isclose(np.linalg.norm(shoulder_mid - hip_mid), 1.0, atol=1e-5)


def test_normalize_marks_low_conf_as_nan():
    pose = make_upright_pose()
    pose[KP['nose'], 2] = 0.05  # below MIN_CONF
    out = normalize_pose_frame(pose, MIN_CONF).reshape(17, 3)
    assert np.isnan(out[KP['nose'], :2]).all(), 'low-conf xy must become NaN'
    assert np.isclose(out[KP['nose'], 2], 0.05), 'conf value itself is preserved'


def test_normalize_without_center_returns_all_nan_xy():
    pose = make_upright_pose(conf=0.05)  # nothing passes MIN_CONF
    out = normalize_pose_frame(pose, MIN_CONF).reshape(17, 3)
    assert np.isnan(out[:, :2]).all()


def test_interpolate_fills_interior_and_clamps_edges():
    seq = np.zeros((5, 51), dtype=np.float32)
    col = 0  # x of nose
    seq[:, col] = [np.nan, 1.0, np.nan, 3.0, np.nan]
    out = interpolate_missing(seq)
    # interior is linear (t=2 between 1.0@t=1 and 3.0@t=3 -> 2.0),
    # edges clamp to nearest valid (t=0 -> 1.0, t=4 -> 3.0)
    assert np.allclose(out[:, col], [1.0, 1.0, 2.0, 3.0, 3.0]), out[:, col]


def test_interpolate_all_nan_column_becomes_zero():
    seq = np.full((4, 51), np.nan, dtype=np.float32)
    out = interpolate_missing(seq)
    assert np.isfinite(out).all()
    assert (out == 0).all()


def test_resample_produces_target_length_and_keeps_endpoints():
    seq = np.linspace(0, 1, 30)[:, None].repeat(51, axis=1).astype(np.float32)
    out = resample_sequence(seq, 60)
    assert out.shape == (60, 51)
    assert np.isclose(out[0, 0], 0.0) and np.isclose(out[-1, 0], 1.0)


def test_timestamp_resample_follows_capture_time_not_frame_count():
    seq = np.array([[0.0], [10.0], [20.0]], dtype=np.float32)
    out = resample_sequence_at_timestamps(seq, [0.0, 1.0, 1.1], 3)
    assert np.allclose(out[:, 0], [0.0, 5.5, 20.0])


def test_add_motion_features_shape_and_clip():
    seq = np.zeros((60, 51), dtype=np.float32)
    seq[1, 0] = 100.0  # huge jump -> velocity must clip to 5
    out = add_motion_features(seq)
    assert out.shape == (60, 85)
    assert out[:, 51:].max() <= 5.0 and out[:, 51:].min() >= -5.0
    assert np.allclose(out[0, 51:], 0.0), 'first-frame velocity must be zero'


def test_full_transform_end_to_end():
    config = FallConfig.from_json(CONFIG_PATH)
    pre = FallPreprocessor(config)
    frames = [make_upright_pose(cy=100 + i * 2) for i in range(20)]
    features = pre.transform(frames)
    assert features is not None
    assert features.shape == (60, 85)
    assert np.isfinite(features).all()
    assert features.dtype == np.float32


def test_transform_skips_sparse_window():
    config = FallConfig.from_json(CONFIG_PATH)
    pre = FallPreprocessor(config)
    frames = [make_upright_pose() for _ in range(config.min_real_points - 1)]
    assert pre.transform(frames) is None, 'sparse window must be skipped, not guessed'


def test_buffer_window_is_time_based():
    buf = TrackKeypointBuffer(window_seconds=1.0, retention_seconds=3.0)
    for i in range(30):
        buf.push('cam1-7', make_upright_pose(), timestamp=i * 0.1)  # 0.0 .. 2.9s
    window = buf.window('cam1-7', now=2.9)
    assert 10 <= len(window) <= 11, f'expected ~1s of 10Hz data, got {len(window)}'


def test_decision_debounce_and_cooldown():
    dec = FallDecision(threshold=0.5, m=2, n=3, cooldown_seconds=10.0)
    assert dec.update('t1', 0.9, now=0.0) is False   # 1/3 positive — not yet
    assert dec.update('t1', 0.2, now=0.3) is False
    assert dec.update('t1', 0.9, now=0.6) is True    # 2/3 positive — fire
    assert dec.update('t1', 0.9, now=0.9) is False   # history cleared after fire
    assert dec.update('t1', 0.9, now=1.2) is False   # 2/3 again but cooldown blocks
    assert dec.update('t1', 0.9, now=11.5) is True   # cooldown expired


def test_heuristic_flags_horizontal_torso():
    upright = [make_upright_pose() for _ in range(5)]
    fallen = []
    for _ in range(5):
        pose = make_upright_pose()
        # rotate torso ~90°: shoulders level with hips, far to the side
        pose[KP['left_shoulder']] = [150, 100, 0.9]
        pose[KP['right_shoulder']] = [155, 105, 0.9]
        fallen.append(pose)
    h = HeuristicFallDetector()
    assert h.predict(upright) == 0.0
    assert h.predict(fallen) == 1.0


def test_posture_classifier_does_not_guess_from_sparse_invalid_poses():
    invalid = make_fallen_pose(conf=0.0)
    classifier = HeuristicFallDetector()
    assert classifier.classify([invalid] * 5) is None
    assert classifier.classify([make_fallen_pose()] * 5) is True
    assert classifier.classify([make_upright_pose()] * 5) is False

def test_fall_warns_once_then_becomes_critical_after_five_seconds_down():
    processor = make_processor()

    result = None
    for timestamp in (0.0, 0.1, 0.2):
        result = processor.process(fall_task(timestamp))

    assert result.warning_fired is True
    assert result.phase == 'WARNING'
    assert result.critical_fired is False

    for timestamp in (5.0, 5.1, 5.2):
        result = processor.process(fall_task(timestamp))

    assert result.critical_fired is True
    assert result.phase == 'CRITICAL'
    assert result.warning_fired is False

    again = processor.process(fall_task(5.3))
    assert again.critical_fired is False

def test_fall_returns_to_normal_after_two_seconds_upright():
    processor = make_processor()
    for timestamp in (0.0, 0.1, 0.2):
        processor.process(fall_task(timestamp))

    result = None
    for timestamp in (0.3, 0.4, 0.5, 0.6, 0.7, 2.3, 2.4, 2.5, 2.7, 2.8):
        result = processor.process(fall_task(timestamp, make_upright_pose()))
        if result.recovered:
            break

    assert result.recovered is True
    assert result.phase == 'NORMAL'
    assert result.warning_fired is False
    assert result.critical_fired is False

if __name__ == '__main__':
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith('test_') and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f'  PASS  {name}')
        except AssertionError as exc:
            failed += 1
            print(f'  FAIL  {name}: {exc}')
    print(f'\n{len(tests) - failed}/{len(tests)} tests passed')
    sys.exit(1 if failed else 0)
