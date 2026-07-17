from collections import deque

import numpy as np


class KeypointBuffer:
    """
    Sliding window of pose keypoints per track, feeding the fall model.
    Each entry is a (17, 3) array: 17 COCO keypoints as (x, y, conf).
    """

    def __init__(self, window_size=30):
        self.window_size = window_size
        self._buffers = {}  # track_id -> deque of (17, 3) arrays

    def push(self, track_id, keypoints):
        if track_id not in self._buffers:
            self._buffers[track_id] = deque(maxlen=self.window_size)
        self._buffers[track_id].append(np.asarray(keypoints, dtype=np.float32))

    def window(self, track_id):
        """Returns (T, 17, 3) array, or None if the buffer is not full yet."""
        buf = self._buffers.get(track_id)
        if buf is None or len(buf) < self.window_size:
            return None
        return np.stack(buf)

    def drop_track(self, track_id):
        self._buffers.pop(track_id, None)


class FallDetector:
    """
    Interface for fall detection. Input is a keypoint window (decided:
    the model consumes keypoint sequences, not image crops).

    Plug the real model in by subclassing and implementing predict();
    the Triton-backed implementation will live here once the model
    weights are delivered (slot reserved: triton_model_repo/fall_model).
    """

    def predict(self, keypoints_window):
        """
        keypoints_window: (T, 17, 3) float32 array for one track.
        Returns fall score in [0, 1].
        """
        raise NotImplementedError


class HeuristicFallDetector(FallDetector):
    """
    Model-free fallback so the pipeline runs end-to-end today.
    Flags a fall when, over the recent frames, the torso tilts far from
    vertical AND the body bbox becomes wider than tall.
    """

    # COCO keypoint indices
    L_SHOULDER, R_SHOULDER, L_HIP, R_HIP = 5, 6, 11, 12

    def __init__(self, angle_threshold_deg=60.0, min_conf=0.3):
        self.angle_threshold_deg = angle_threshold_deg
        self.min_conf = min_conf

    def predict(self, keypoints_window):
        recent = keypoints_window[-5:]
        votes = []

        for kps in recent:
            parts = kps[[self.L_SHOULDER, self.R_SHOULDER, self.L_HIP, self.R_HIP]]
            if (parts[:, 2] < self.min_conf).any():
                continue

            shoulder_mid = (parts[0, :2] + parts[1, :2]) / 2
            hip_mid = (parts[2, :2] + parts[3, :2]) / 2
            spine = shoulder_mid - hip_mid

            # Angle between the spine vector and the vertical axis
            vertical = np.array([0.0, -1.0])
            norm = np.linalg.norm(spine)
            if norm == 0:
                continue
            cos_angle = np.clip(np.dot(spine / norm, vertical), -1.0, 1.0)
            angle_deg = np.degrees(np.arccos(cos_angle))
            votes.append(angle_deg > self.angle_threshold_deg)

        if not votes:
            return 0.0
        return float(sum(votes)) / len(votes)
