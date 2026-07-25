"""
Fall detection branch — 4-block pipeline matching the delivered model.

The model (Compact Temporal Transformer, trained in notebookb0cb845271.ipynb on
Multiple Cameras Fall Dataset, keypoints from YOLO11n-pose) consumes a window of
shape (60, 85): 51 normalized pose values (17 COCO keypoints x x,y,conf) plus
34 joint velocities.

Preprocessing here MUST mirror the training notebook exactly — any drift
silently degrades accuracy without raising errors. The functions
`normalize_pose_frame`, `interpolate_missing`, `resample_sequence` and
`add_motion_features` are line-for-line ports of the notebook (pandas replaced
with equivalent numpy; verified by unit tests in tests/test_fall_preprocessing.py).

`weights/fall_model/inference_config.json` is the source of truth for keypoint
order, min confidence, window length and decision threshold.

Blocks:
    [1] TrackKeypointBuffer  — timestamp-based ring buffer per track
    [2] FallPreprocessor     — raw keypoint frames -> (60, 85) tensor
    [3] TritonFallDetector   — gRPC call to the fall_model on Triton
    [4] FallDecision         — threshold + M-of-N debounce + per-track cooldown

HeuristicFallDetector is kept as an independent safety net (WARNING severity):
the model's fall recall is 0.45 at the shipped threshold, so a second detector
with different failure modes meaningfully reduces missed falls.
"""
import json
import math
from collections import deque
from pathlib import Path

import numpy as np

COCO_KEYPOINTS = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
]
KP = {name: i for i, name in enumerate(COCO_KEYPOINTS)}

_XY_COLS = [i for i in range(51) if i % 3 != 2]
_CONF_COLS = [i for i in range(51) if i % 3 == 2]


class FallConfig:
    """Inference contract exported by the training notebook."""

    def __init__(self, max_frames, num_features, min_keypoint_confidence,
                 threshold, window_seconds=1.0, min_real_points=8):
        self.max_frames = int(max_frames)
        self.num_features = int(num_features)
        self.min_kp_conf = float(min_keypoint_confidence)
        self.threshold = float(threshold)
        self.window_seconds = float(window_seconds)
        self.min_real_points = int(min_real_points)

    @classmethod
    def from_json(cls, path):
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
        notes = raw.get('_notes', {})
        cfg = cls(
            max_frames=raw['max_frames'],
            num_features=raw['num_features'],
            min_keypoint_confidence=raw['min_keypoint_confidence'],
            threshold=raw['threshold'],
            window_seconds=notes.get('window_seconds_realtime', 1.0),
            min_real_points=notes.get('min_real_points_per_window', 8),
        )
        if raw['keypoint_order'] != COCO_KEYPOINTS:
            raise ValueError('keypoint_order in config differs from COCO_KEYPOINTS')
        return cfg


# ---------------------------------------------------------------------------
# Notebook-port preprocessing (do not "improve" without retraining the model)
# ---------------------------------------------------------------------------

def _midpoint(pose, left_name, right_name, min_conf):
    pts = []
    for name in (left_name, right_name):
        p = pose[KP[name]]
        if np.isfinite(p[:2]).all() and p[2] >= min_conf:
            pts.append(p[:2])
    return np.mean(pts, axis=0) if pts else None


def normalize_pose_frame(pose_17x3, min_conf):
    """(17, 3) raw pixels -> (51,) hip-centered, torso-scaled; invalid xy = NaN."""
    pose = np.asarray(pose_17x3, dtype=np.float32).reshape(17, 3).copy()
    hip = _midpoint(pose, 'left_hip', 'right_hip', min_conf)
    shoulder = _midpoint(pose, 'left_shoulder', 'right_shoulder', min_conf)
    center = hip if hip is not None else shoulder
    if center is None:
        out = np.full_like(pose, np.nan)
        out[:, 2] = np.nan_to_num(pose[:, 2], nan=0.0)
        return out.reshape(-1)

    scale_candidates = []
    if hip is not None and shoulder is not None:
        scale_candidates.append(np.linalg.norm(shoulder - hip))
    for a, b in [('left_shoulder', 'right_shoulder'), ('left_hip', 'right_hip')]:
        pa, pb = pose[KP[a]], pose[KP[b]]
        if pa[2] >= min_conf and pb[2] >= min_conf \
                and np.isfinite(pa[:2]).all() and np.isfinite(pb[:2]).all():
            scale_candidates.append(np.linalg.norm(pa[:2] - pb[:2]))
    scale = next((s for s in scale_candidates if np.isfinite(s) and s > 1e-4), None)
    if scale is None:
        out = np.full_like(pose, np.nan)
        out[:, 2] = np.nan_to_num(pose[:, 2], nan=0.0)
        return out.reshape(-1)

    valid = (pose[:, 2] >= min_conf) & np.isfinite(pose[:, :2]).all(axis=1)
    pose[:, :2] = (pose[:, :2] - center) / scale
    pose[~valid, :2] = np.nan
    pose[:, 2] = np.nan_to_num(pose[:, 2], nan=0.0)
    return pose.reshape(-1)


def interpolate_missing(sequence_51):
    """Time-interpolate NaN xy (edges clamped to nearest valid), conf -> [0, 1]."""
    seq = np.asarray(sequence_51, dtype=np.float32).copy()
    t = np.arange(len(seq))
    for col in _XY_COLS:
        values = seq[:, col]
        valid = np.isfinite(values)
        if not valid.any():
            seq[:, col] = 0.0
        elif not valid.all():
            seq[:, col] = np.interp(t, t[valid], values[valid])
    conf = seq[:, _CONF_COLS]
    seq[:, _CONF_COLS] = np.clip(np.nan_to_num(conf, nan=0.0), 0.0, 1.0)
    return seq


def resample_sequence(sequence, target_len):
    sequence = np.asarray(sequence, dtype=np.float32)
    if len(sequence) == target_len:
        return sequence.copy()
    old_t = np.linspace(0.0, 1.0, len(sequence))
    new_t = np.linspace(0.0, 1.0, target_len)
    return np.stack(
        [np.interp(new_t, old_t, sequence[:, j]) for j in range(sequence.shape[1])],
        axis=1,
    ).astype(np.float32)


def add_motion_features(sequence_51):
    """(T, 51) -> (T, 85): append per-joint xy velocity clipped to [-5, 5]."""
    xy = sequence_51[:, _XY_COLS]
    velocity = np.diff(xy, axis=0, prepend=xy[:1])
    velocity = np.clip(velocity, -5.0, 5.0)
    return np.concatenate([sequence_51, velocity], axis=1).astype(np.float32)


# ---------------------------------------------------------------------------
# Runtime blocks
# ---------------------------------------------------------------------------

class TrackKeypointBuffer:
    """[1] Timestamp-based sliding window of raw (17, 3) keypoints per track."""

    def __init__(self, window_seconds=1.0, retention_seconds=3.0):
        self.window_seconds = float(window_seconds)
        self.retention_seconds = float(retention_seconds)
        self._buffers = {}  # track_id -> deque of (timestamp, (17, 3) array)

    def push(self, track_id, keypoints_17x3, timestamp):
        buf = self._buffers.setdefault(track_id, deque())
        buf.append((float(timestamp), np.asarray(keypoints_17x3, dtype=np.float32)))
        cutoff = timestamp - self.retention_seconds
        while buf and buf[0][0] < cutoff:
            buf.popleft()

    def window(self, track_id, now):
        """Frames inside [now - window_seconds, now], oldest first."""
        buf = self._buffers.get(track_id)
        if not buf:
            return []
        start = now - self.window_seconds
        return [kps for ts, kps in buf if ts >= start]

    def drop_track(self, track_id):
        self._buffers.pop(track_id, None)

    def prune(self, now):
        stale = [tid for tid, buf in self._buffers.items()
                 if not buf or buf[-1][0] < now - self.retention_seconds]
        for tid in stale:
            del self._buffers[tid]


class FallPreprocessor:
    """[2] Raw keypoint frames -> the exact (max_frames, 85) tensor of training."""

    def __init__(self, config: FallConfig):
        self.config = config

    def transform(self, frames):
        """
        frames: list of (17, 3) raw-pixel keypoint arrays, oldest first.
        Returns (max_frames, num_features) float32, or None when the window is
        too sparse to trust (caller should skip prediction, not guess).
        """
        if len(frames) < self.config.min_real_points:
            return None
        normalized = np.stack(
            [normalize_pose_frame(f, self.config.min_kp_conf) for f in frames]
        )
        sequence = resample_sequence(
            interpolate_missing(normalized), self.config.max_frames
        )
        features = add_motion_features(sequence)
        if features.shape != (self.config.max_frames, self.config.num_features):
            raise ValueError(f'Unexpected feature shape {features.shape}')
        return features


class TritonFallDetector:
    """[3] gRPC call to fall_model on Triton (Keras model converted to ONNX)."""

    def __init__(self, url='localhost:8001', model_name='fall_model',
                 input_name='pose_sequence', output_name='fall_probability'):
        import tritonclient.grpc as grpcclient
        self._grpcclient = grpcclient
        self.client = grpcclient.InferenceServerClient(url=url)
        self.model_name = model_name
        self.input_name = input_name
        self.output_name = output_name

    def predict(self, features_60x85):
        batch = np.expand_dims(features_60x85.astype(np.float32), axis=0)
        inputs = [self._grpcclient.InferInput(self.input_name, batch.shape, 'FP32')]
        inputs[0].set_data_from_numpy(batch)
        outputs = [self._grpcclient.InferRequestedOutput(self.output_name)]
        response = self.client.infer(
            model_name=self.model_name, inputs=inputs, outputs=outputs
        )
        return float(response.as_numpy(self.output_name).ravel()[0])


class FallDecision:
    """[4] Threshold + M-of-N debounce + per-track cooldown.

    False-alarm control lives HERE (debounce), not in the threshold — the
    threshold is tuned for recall (F2) and adjustable at runtime.
    """

    def __init__(self, threshold, m=2, n=3, cooldown_seconds=30.0):
        self.threshold = float(threshold)
        self.m = int(m)
        self.n = int(n)
        self.cooldown_seconds = float(cooldown_seconds)
        self._history = {}    # track_id -> deque of bool (last n predictions)
        self._last_fired = {}  # track_id -> timestamp

    def update(self, track_id, probability, now):
        """Returns True when a fall alert should fire for this track."""
        hist = self._history.setdefault(track_id, deque(maxlen=self.n))
        hist.append(probability >= self.threshold)
        if sum(hist) < self.m:
            return False
        last = self._last_fired.get(track_id)
        if last is not None and now - last < self.cooldown_seconds:
            return False
        self._last_fired[track_id] = now
        hist.clear()
        return True

    def drop_track(self, track_id):
        self._history.pop(track_id, None)
        self._last_fired.pop(track_id, None)


class HeuristicFallDetector:
    """
    Model-free safety net (WARNING severity), independent failure modes from
    the transformer: flags when the torso tilts far from vertical over the
    recent frames. Operates on RAW keypoints, not the normalized tensor.
    """

    L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

    def __init__(self, angle_threshold_deg=60.0, min_conf=0.3):
        self.angle_threshold_deg = angle_threshold_deg
        self.min_conf = min_conf

    def predict(self, frames):
        """frames: list of (17, 3) raw keypoints. Returns vote ratio in [0, 1]."""
        votes = []
        for kps in frames[-5:]:
            kps = np.asarray(kps, dtype=np.float32)
            parts = kps[[self.L_SHOULDER, self.R_SHOULDER, self.L_HIP, self.R_HIP]]
            if (parts[:, 2] < self.min_conf).any():
                continue
            shoulder_mid = (parts[0, :2] + parts[1, :2]) / 2
            hip_mid = (parts[2, :2] + parts[3, :2]) / 2
            spine = shoulder_mid - hip_mid
            norm = np.linalg.norm(spine)
            if norm == 0:
                continue
            cos_angle = np.clip(np.dot(spine / norm, np.array([0.0, -1.0])), -1.0, 1.0)
            votes.append(math.degrees(math.acos(cos_angle)) > self.angle_threshold_deg)
        if not votes:
            return 0.0
        return float(sum(votes)) / len(votes)
