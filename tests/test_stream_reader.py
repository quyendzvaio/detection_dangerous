import pytest

from ai_engine.ingest.camera_stream import CameraConfig
from ai_engine.ingest.stream_reader import FileReader, MediaMtxRtspReader, reader_for


def test_reader_for_file_uses_file_adapter():
    reader = reader_for(CameraConfig(1, "demo", "test.mp4"))
    assert isinstance(reader, FileReader)


def test_reader_for_rtsp_uses_mediamtx_adapter():
    config = CameraConfig(1, "cam", "rtsp://mediamtx/live/cam")
    assert isinstance(reader_for(config, require_mediamtx=True), MediaMtxRtspReader)


def test_mediamtx_reader_rejects_non_rtsp():
    with pytest.raises(ValueError):
        MediaMtxRtspReader(CameraConfig(1, "cam", "video.mp4"))

