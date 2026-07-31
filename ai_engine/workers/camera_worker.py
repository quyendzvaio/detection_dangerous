"""
Camera worker — one independent process per camera (multiprocessing).

Replaces the old ultralytics `model.track()` monolith with explicit stages so
inference lives on Triton and tracking runs locally:

    USB decode (latest-frame) → PoseClient (gRPC) → BoxMOT → TrackedPerson[]

The worker holds NO model. Each frame it produces a list of TrackedPerson
(bbox, stable track_id, 17 keypoints, timestamp) — the single upstream feed the
four analytics branches (Re-ID, PPE, Zone, Fall) consume.

Real-time invariants (docs/PRODUCT_PIPELINE.md):
  - latest-frame-only: grab() drains the driver buffer, only the newest frame
    is decoded — inference falling behind drops frames instead of queueing.
  - the pose call is synchronous, so exactly one request per worker is ever
    in flight → Triton never backlogs more than (num_cameras) pose requests.

Standalone demo (needs Triton running + a camera):
    python3 -m ai_engine.workers.camera_worker --source 0 --show
"""
import argparse
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

from ai_engine.inference.pose_client import PoseClient

# COCO skeleton for drawing (pairs of keypoint indices)
_SKELETON = [
    (5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12),
    (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2), (1, 3), (2, 4),
]


@dataclass
class TrackedPerson:
    track_id: str                 # camera-prefixed, e.g. "cam1-7"
    bbox: np.ndarray              # (4,) xyxy in original frame coords
    keypoints: np.ndarray         # (17, 3) x, y, conf
    conf: float
    timestamp: float


@dataclass
class CameraStream:
    """USB camera reader forcing MJPG + resolution, always yielding the newest frame."""
    source: object
    width: int = 1280
    height: int = 720
    fps: int = 25
    _cap: cv2.VideoCapture = field(default=None, init=False, repr=False)

    def open(self):
        # int-like source => USB device index; else a path/URL
        src = int(self.source) if str(self.source).isdigit() else self.source
        cap = cv2.VideoCapture(src)
        if isinstance(src, int):
            # MJPG is mandatory: two raw YUYV streams exceed USB bandwidth.
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            cap.set(cv2.CAP_PROP_FPS, self.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise RuntimeError(f'Không mở được camera: {self.source}')
        self._cap = cap
        return self

    def read_latest(self):
        """Drain buffered frames, return only the most recent (or None)."""
        cap = self._cap
        ok = cap.grab()          # cheap: advance to newest available frame
        if not ok:
            return None
        ok, frame = cap.retrieve()
        return frame if ok else None

    def release(self):
        if self._cap is not None:
            self._cap.release()


def draw_overlay(frame, people):
    for p in people:
        x1, y1, x2, y2 = p.bbox.astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, p.track_id, (x1, y1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        kp = p.keypoints
        for a, b in _SKELETON:
            if kp[a, 2] > 0.3 and kp[b, 2] > 0.3:
                cv2.line(frame, tuple(kp[a, :2].astype(int)),
                         tuple(kp[b, :2].astype(int)), (255, 180, 0), 2)
        for x, y, c in kp:
            if c > 0.3:
                cv2.circle(frame, (int(x), int(y)), 3, (0, 200, 255), -1)
    return frame


def make_tracker(frame_rate=25):
    """BoT-SORT with appearance Re-ID OFF (we have a dedicated Re-ID branch)
    and camera-motion-compensation OFF (static factory cameras)."""
    from boxmot.trackers.bbox.botsort import BotSort
    return BotSort(with_reid=False, use_cmc=False, frame_rate=frame_rate)


class CameraWorker:
    def __init__(self, camera_id, source, triton_url='localhost:8001',
                 width=1280, height=720, fps=25, conf_thresh=0.25):
        self.camera_id = camera_id
        self.stream = CameraStream(source, width, height, fps)
        self.pose = PoseClient(url=triton_url, conf_thresh=conf_thresh)
        self.tracker = make_tracker(fps)

    def _to_tracked(self, tracks, keypoints, now):
        """Map BoxMOT tracks (N,8) back to their keypoints via det_index (col 7)."""
        people = []
        for row in np.asarray(tracks):
            x1, y1, x2, y2, track_id, conf, _cls, det_idx = row[:8]
            det_idx = int(det_idx)
            kp = keypoints[det_idx] if 0 <= det_idx < len(keypoints) \
                else np.zeros((17, 3), np.float32)
            people.append(TrackedPerson(
                track_id=f'{self.camera_id}-{int(track_id)}',
                bbox=np.array([x1, y1, x2, y2], np.float32),
                keypoints=kp,
                conf=float(conf),
                timestamp=now,
            ))
        return people

    def process_frame(self, frame):
        """One frame → list[TrackedPerson]. Timestamp taken at capture."""
        now = time.time()
        boxes, scores, keypoints = self.pose.infer(frame)
        if len(boxes) == 0:
            dets = np.empty((0, 6), np.float32)
        else:
            cls_col = np.zeros((len(boxes), 1), np.float32)  # single class: person
            dets = np.concatenate([boxes, scores[:, None], cls_col], axis=1)
        tracks = self.tracker.update(dets, frame)
        return self._to_tracked(tracks, keypoints, now)

    def run(self, on_people=None, show=False, stop_event=None):
        self.stream.open()
        frames, t0 = 0, time.time()
        try:
            while stop_event is None or not stop_event.is_set():
                frame = self.stream.read_latest()
                if frame is None:
                    time.sleep(0.005)
                    continue
                people = self.process_frame(frame)
                if on_people is not None:
                    on_people(people)
                frames += 1
                if show:
                    draw_overlay(frame, people)
                    fps = frames / (time.time() - t0 + 1e-9)
                    cv2.putText(frame, f'{self.camera_id}  {fps:4.1f} FPS  '
                                f'{len(people)} person', (12, 28),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                    cv2.imshow(f'camera_worker [{self.camera_id}]', frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
        finally:
            self.stream.release()
            if show:
                cv2.destroyAllWindows()


def run_camera_worker(camera_id, source, triton_url='localhost:8001',
                      on_people=None, show=False, stop_event=None):
    """multiprocessing.Process target."""
    worker = CameraWorker(camera_id, source, triton_url=triton_url)
    worker.run(on_people=on_people, show=show, stop_event=stop_event)


def _main():
    ap = argparse.ArgumentParser(description='Camera worker demo (cần Triton chạy sẵn)')
    ap.add_argument('--source', default='0', help='USB index (0) hoặc path video')
    ap.add_argument('--camera-id', default='cam1')
    ap.add_argument('--triton-url', default='localhost:8001')
    ap.add_argument('--show', action='store_true', help='hiện cửa sổ overlay')
    args = ap.parse_args()
    run_camera_worker(args.camera_id, args.source,
                      triton_url=args.triton_url, show=args.show)


if __name__ == '__main__':
    _main()
