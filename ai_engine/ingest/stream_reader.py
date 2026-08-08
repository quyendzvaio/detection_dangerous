"""Deep stream input seam for local, replay and MediaMTX inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ai_engine.ingest.camera_stream import CameraConfig, CameraStream


@dataclass(frozen=True)
class StreamMetrics:
    source: str
    reconnects: int
    frames_read: int
    last_frame_at: float | None


class StreamReader(Protocol):
    """Small interface consumed by the inference worker."""

    def open(self) -> None: ...

    def read(self): ...

    def frame_interval_seconds(self) -> float: ...

    def release(self) -> None: ...


class FileReader(CameraStream):
    """Replay adapter; keeps the legacy OpenCV/file timing semantics."""

    def __init__(self, config: CameraConfig):
        if config.is_live_source:
            raise ValueError("FileReader requires a local file source")
        super().__init__(config)


class MediaMtxRtspReader(CameraStream):
    """RTSP adapter for a MediaMTX path.

    The reader deliberately delegates decoding to the existing CameraStream
    implementation so color conversion, frame dimensions and reconnect
    behaviour remain unchanged during migration.
    """

    def __init__(self, config: CameraConfig):
        source = str(config.source).lower()
        if not source.startswith(("rtsp://", "rtsps://")):
            raise ValueError("MediaMtxRtspReader requires an RTSP/RTSPS source")
        super().__init__(config)


def reader_for(config: CameraConfig, *, require_mediamtx: bool = False) -> StreamReader:
    """Select an adapter without changing the legacy CameraIngest API."""

    if require_mediamtx:
        return MediaMtxRtspReader(config)
    if config.is_live_source:
        return MediaMtxRtspReader(config) if str(config.source).lower().startswith(("rtsp://", "rtsps://")) else CameraStream(config)
    return FileReader(config)

