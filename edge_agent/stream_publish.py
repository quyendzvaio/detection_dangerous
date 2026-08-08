"""FFmpeg command construction for site-to-MediaMTX RTSP publishing."""

from __future__ import annotations

from dataclasses import dataclass
import subprocess

from ai_engine.quality_contract import QUALITY_CONTRACT


@dataclass(frozen=True)
class PublishSpec:
    source: str
    target_rtsp_url: str
    source_is_device: bool = False
    width: int = QUALITY_CONTRACT.camera_width
    height: int = QUALITY_CONTRACT.camera_height
    fps: int = QUALITY_CONTRACT.camera_fps


def build_ffmpeg_publish_command(spec: PublishSpec) -> list[str]:
    if not spec.target_rtsp_url.startswith(("rtsp://", "rtsps://")):
        raise ValueError("target must be an RTSP/RTSPS MediaMTX URL")
    if spec.source_is_device:
        input_args = [
            "-f", "v4l2",
            "-input_format", "mjpeg",
            "-video_size", f"{spec.width}x{spec.height}",
            "-framerate", str(spec.fps),
            "-i", spec.source,
        ]
    else:
        input_args = ["-i", spec.source]
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-fflags", "nobuffer", "-flags", "low_delay",
        *input_args,
        "-an", "-c:v", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
        spec.target_rtsp_url,
    ]


class StreamProcessManager:
    """Own one reconnectable FFmpeg publisher per configured camera."""

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}

    def ensure(self, camera_key: str, spec: PublishSpec) -> None:
        current = self._processes.get(camera_key)
        if current is not None and current.poll() is None:
            return
        self.stop(camera_key)
        self._processes[camera_key] = subprocess.Popen(
            build_ffmpeg_publish_command(spec),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    def stop(self, camera_key: str) -> None:
        process = self._processes.pop(camera_key, None)
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    def close(self) -> None:
        for camera_key in list(self._processes):
            self.stop(camera_key)

