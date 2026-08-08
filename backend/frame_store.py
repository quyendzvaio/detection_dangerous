"""Thread-safe latest-frame cache for the single-process MVP backend."""

from threading import Lock


class LatestFrameStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._frames: dict[tuple[int, bool], bytes] = {}

    def put(self, camera_id: int, overlay: bool, jpeg: bytes) -> None:
        with self._lock:
            self._frames[(camera_id, overlay)] = jpeg

    def get(self, camera_id: int, overlay: bool) -> bytes | None:
        with self._lock:
            return self._frames.get((camera_id, overlay))

    def remove(self, camera_id: int) -> None:
        with self._lock:
            self._frames.pop((camera_id, False), None)
            self._frames.pop((camera_id, True), None)


latest_frames = LatestFrameStore()
