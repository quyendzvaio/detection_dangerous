"""Layer 0 camera ingest: capture frames, keep only the latest, reconnect safely."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import cv2

from ai_engine.contracts.event_schema import CapturedFrame
from ai_engine.ingest.latest_frame import LatestFrameBuffer

StatusCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class CameraConfig:
    camera_id: int
    camera_key: str
    source: str | int
    width: int = 1280
    height: int = 720
    fps: int = 25
    fourcc: str = "MJPG"
    reconnect_backoff_seconds: float = 1.0

    @property
    def is_usb_source(self) -> bool:
        return isinstance(self.source, int) or str(self.source).startswith(("/dev/video", "/dev/v4l/by-id/"))

    @property
    def is_live_source(self) -> bool:
        return self.is_usb_source or str(self.source).lower().startswith(
            ("rtsp://", "http://", "https://")
        )


@dataclass
class CameraStream:
    """OpenCV source wrapper. Its reader is owned by one capture thread."""

    config: CameraConfig
    _cap: cv2.VideoCapture | None = field(default=None, init=False, repr=False)

    def open(self) -> None:
        source = self.config.source
        if self.config.is_usb_source:
            cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(source)
        else:
            cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            cap.release()
            raise RuntimeError(f"Cannot open camera source: {source}")
        if self.config.is_usb_source:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.config.fourcc))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
            cap.set(cv2.CAP_PROP_FPS, self.config.fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap

    def read(self):
        if self._cap is None:
            raise RuntimeError("CameraStream must be opened before reading")
        ok, frame = self._cap.read()
        return frame if ok else None

    def frame_interval_seconds(self) -> float:
        """Source frame interval; only used to pace finite video-file demos."""
        if self._cap is None:
            return 1.0 / max(self.config.fps, 1)
        fps = float(self._cap.get(cv2.CAP_PROP_FPS))
        return 1.0 / (fps if fps > 0.0 else self.config.fps)

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class CameraIngest:
    """Owns one capture thread and emits CapturedFrame to a LatestFrameBuffer."""

    def __init__(
        self,
        config: CameraConfig,
        buffer: Optional[LatestFrameBuffer] = None,
        status_callback: Optional[StatusCallback] = None,
    ) -> None:
        self.config = config
        self.buffer = buffer or LatestFrameBuffer()
        self._status_callback = status_callback
        self._stream = CameraStream(config)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.reconnect_count = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("CameraIngest is already running")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._capture_loop,
            name=f"capture-{self.config.camera_key}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self._stream.release()
        self.buffer.close()

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _status(self, status: str, message: str) -> None:
        if self._status_callback is not None:
            self._status_callback(status, message)

    def _capture_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._status("CONNECTING", f"Opening {self.config.source}")
                self._stream.open()
                self._status("ONLINE", "Camera is producing frames")
                if self._read_until_interrupted():
                    break
                if self.config.is_live_source and not self._stop.is_set():
                    self._status("OFFLINE", "Frame read failed; reconnecting")
            except Exception as exc:
                self._status("OFFLINE", str(exc))
            finally:
                self._stream.release()

            if not self.config.is_live_source:
                self._status("EOF", "Video file ended")
                break
            self.reconnect_count += 1
            if self._stop.wait(self.config.reconnect_backoff_seconds):
                break
        self.buffer.close()

    def _read_until_interrupted(self) -> bool:
        while not self._stop.is_set():
            frame = self._stream.read()
            if frame is None:
                return False
            height, width = frame.shape[:2]
            captured = CapturedFrame(
                camera_id=self.config.camera_id,
                camera_key=self.config.camera_key,
                captured_at=time.time(),
                frame_bgr=frame,
                frame_width=width,
                frame_height=height,
            )
            self.buffer.publish(captured)
            if not self.config.is_live_source:
                # File input has no hardware clock; preserve its native pace so
                # visual demos and temporal fall windows use real elapsed time.
                if self._stop.wait(self._stream.frame_interval_seconds()):
                    return True
        return True
