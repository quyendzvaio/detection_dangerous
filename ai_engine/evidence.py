"""Asynchronous evidence capture and direct-to-object-storage upload via backend signing."""
from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ai_engine.contracts.event_schema import FallDetectedEvent, SafetyEvent, TrackedFrame

log = logging.getLogger(__name__)


class _PermanentRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvidenceFile:
    kind: str
    content_type: str
    path: Path


@dataclass(frozen=True)
class EvidenceJob:
    event_id: str
    files: tuple[EvidenceFile, ...]
    manifest_path: Path | None = None


class EvidenceUploader:
    """Durable spool consumer: obtain upload lease, PUT bytes, then complete/fail."""

    def __init__(
        self,
        backend_event_url: str,
        service_token: str,
        spool_dir: Path,
        *,
        session=None,
        request_timeout: float = 10.0,
        upload_timeout: float = 90.0,
        retries: int = 4,
        backoff_seconds: float = 0.5,
        on_ready: Callable[[str, str | None, str | None], None] | None = None,
    ) -> None:
        self.internal_base = backend_event_url.rsplit("/", 1)[0]
        self.service_token = service_token
        self.spool_dir = Path(spool_dir)
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self._session = session
        self.request_timeout = request_timeout
        self.upload_timeout = upload_timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.on_ready = on_ready
        self.sent_count = 0
        self.failed_count = 0
        self._jobs: queue.Queue[EvidenceJob] = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="evidence-uploader", daemon=True
        )
        self._load_manifests()
        self._thread.start()

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def submit(self, job: EvidenceJob) -> None:
        manifest = job.manifest_path or self.spool_dir / f"{job.event_id}.job.json"
        payload = {
            "event_id": job.event_id,
            "files": [
                {
                    "kind": item.kind,
                    "content_type": item.content_type,
                    "path": str(item.path.resolve()),
                }
                for item in job.files
            ],
        }
        temporary = manifest.with_suffix(manifest.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")))
        temporary.replace(manifest)
        self._jobs.put(EvidenceJob(job.event_id, job.files, manifest))

    def _load_manifests(self) -> None:
        for manifest in sorted(self.spool_dir.glob("*.job.json")):
            try:
                payload = json.loads(manifest.read_text())
                files = tuple(
                    EvidenceFile(item["kind"], item["content_type"], Path(item["path"]))
                    for item in payload["files"]
                )
                if files and all(item.path.is_file() for item in files):
                    self._jobs.put(EvidenceJob(payload["event_id"], files, manifest))
            except Exception:
                log.exception("Invalid evidence manifest retained at %s", manifest)

    def _run(self) -> None:
        while not self._stop.is_set() or not self._jobs.empty():
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self._upload_job(job):
                    self.sent_count += 1
                    self._remove_job(job)
                else:
                    self.failed_count += 1
            except Exception:
                self.failed_count += 1
                log.exception("Evidence upload failed for event %s", job.event_id)
            finally:
                self._jobs.task_done()

    def _upload_job(self, job: EvidenceJob) -> bool:
        session = self._get_session()
        headers = {"Authorization": f"Bearer {self.service_token}"}
        specs = [
            {
                "kind": item.kind,
                "content_type": item.content_type,
                "size_bytes": item.path.stat().st_size,
            }
            for item in job.files
        ]
        presign_url = f"{self.internal_base}/events/{job.event_id}/evidence/presign"
        presign = self._request_json(
            "post",
            presign_url,
            headers=headers,
            json={"objects": specs},
            retry_statuses={404, 408, 425, 429},
        )
        if presign is None:
            return True

        uploads = {item["kind"]: item for item in presign["uploads"]}
        completed = []
        try:
            for local_file in job.files:
                remote = uploads[local_file.kind]
                etag = self._put_file(
                    session,
                    remote["upload_url"],
                    remote.get("upload_headers", {}),
                    local_file,
                )
                completed.append(
                    {
                        "evidence_id": remote["evidence_id"],
                        "size_bytes": local_file.path.stat().st_size,
                        "etag": etag,
                    }
                )
            complete_url = (
                f"{self.internal_base}/events/{job.event_id}/evidence/complete"
            )
            completed_response = self._request_json(
                "post",
                complete_url,
                headers=headers,
                json={"objects": completed},
                retry_statuses={408, 425, 429},
            )
            # Forward short-lived signed download URLs to the customer host
            # (via the MQTT event bus) so local evidence can be pulled.
            if completed_response is not None and self.on_ready is not None:
                image_url = completed_response.get("image_download_url")
                video_url = completed_response.get("video_download_url")
                if image_url or video_url:
                    try:
                        self.on_ready(job.event_id, image_url, video_url)
                    except Exception:
                        log.exception(
                            "Could not forward evidence URLs for %s", job.event_id
                        )
            return True
        except Exception as exc:
            failed_ids = [item["evidence_id"] for item in uploads.values()]
            try:
                self._request_json(
                    "post",
                    f"{self.internal_base}/events/{job.event_id}/evidence/fail",
                    headers=headers,
                    json={
                        "objects": [
                            {"evidence_id": item_id, "reason": str(exc)[:1000]}
                            for item_id in failed_ids
                        ]
                    },
                    retry_statuses={408, 425, 429},
                )
            except Exception:
                log.exception("Could not report evidence failure for %s", job.event_id)
            log.error("Evidence files retained for retry: %s", job.event_id)
            return False

    def _request_json(self, method: str, url: str, *, retry_statuses: set[int], **kwargs):
        session = self._get_session()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = getattr(session, method)(
                    url, timeout=self.request_timeout, **kwargs
                )
                if 200 <= response.status_code < 300:
                    return response.json()
                if response.status_code == 409 and "already uploaded" in response.text.lower():
                    return None
                error = RuntimeError(
                    f"HTTP {response.status_code} from {url}: {response.text[:500]}"
                )
                if response.status_code not in retry_statuses and response.status_code < 500:
                    raise _PermanentRequestError(str(error))
                last_error = error
            except _PermanentRequestError:
                raise
            except Exception as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError(f"request failed after {self.retries + 1} attempts") from last_error

    def _put_file(
        self, session, upload_url: str, upload_headers: dict[str, str], item: EvidenceFile
    ) -> str | None:
        headers = dict(upload_headers)
        headers.setdefault("Content-Type", item.content_type)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with item.path.open("rb") as stream:
                    response = session.put(
                        upload_url,
                        data=stream,
                        headers=headers,
                        timeout=self.upload_timeout,
                    )
                if 200 <= response.status_code < 300:
                    return response.headers.get("ETag")
                last_error = RuntimeError(
                    f"object storage PUT returned HTTP {response.status_code}: {response.text[:500]}"
                )
                if response.status_code < 500 and response.status_code not in {408, 425, 429}:
                    break
            except Exception as exc:
                last_error = exc
            if attempt < self.retries:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError(f"object storage upload failed for {item.kind}") from last_error

    @staticmethod
    def _remove_job(job: EvidenceJob) -> None:
        for item in job.files:
            item.path.unlink(missing_ok=True)
        if job.manifest_path is not None:
            job.manifest_path.unlink(missing_ok=True)

    def close(self, timeout: float = 20.0) -> None:
        deadline = time.monotonic() + timeout
        while self._jobs.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        self._stop.set()
        self._thread.join(timeout=1.0)

    def stats(self) -> dict[str, int]:
        return {
            "uploaded": self.sent_count,
            "failed": self.failed_count,
            "pending": self._jobs.qsize(),
        }


@dataclass(frozen=True)
class _FrameInput:
    captured_at: float
    frame_bgr: np.ndarray
    bboxes: dict[str, np.ndarray]


@dataclass(frozen=True)
class _FrameSample:
    captured_at: float
    jpeg: bytes
    bboxes: dict[str, np.ndarray]


@dataclass
class _PendingFall:
    event: FallDetectedEvent
    image_path: Path
    samples: list[_FrameSample]
    deadline: float


class EvidenceCapture:
    """Sample frames off the hot path and create event-specific JPEG/MP4 files."""

    def __init__(
        self,
        camera_key: str,
        spool_dir: Path,
        submit_job: Callable[[EvidenceJob], None],
        *,
        sample_fps: float = 8.0,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0,
        jpeg_quality: int = 82,
    ) -> None:
        self.camera_key = camera_key
        self.spool_dir = Path(spool_dir) / camera_key
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.submit_job = submit_job
        self.sample_fps = float(sample_fps)
        self.pre_seconds = float(pre_seconds)
        self.post_seconds = float(post_seconds)
        self.jpeg_quality = int(jpeg_quality)
        self._frames: queue.Queue[_FrameInput] = queue.Queue(maxsize=2)
        self._events: queue.Queue[SafetyEvent] = queue.Queue()
        self._ring: deque[_FrameSample] = deque()
        self._pending_falls: list[_PendingFall] = []
        self._last_enqueued_at = float("-inf")
        self._stop = threading.Event()
        self.dropped_frames = 0
        self._thread = threading.Thread(
            target=self._run, name=f"evidence-capture-{camera_key}", daemon=True
        )
        self._thread.start()

    def observe(self, tracked: TrackedFrame) -> None:
        interval = 1.0 / max(self.sample_fps, 0.1)
        if tracked.captured_at - self._last_enqueued_at < interval:
            return
        self._last_enqueued_at = tracked.captured_at
        item = _FrameInput(
            tracked.captured_at,
            tracked.frame_bgr.copy(),
            {person.track_id: person.bbox_xyxy.copy() for person in tracked.persons},
        )
        try:
            self._frames.put_nowait(item)
        except queue.Full:
            try:
                self._frames.get_nowait()
                self._frames.task_done()
                self.dropped_frames += 1
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(item)
            except queue.Full:
                self.dropped_frames += 1

    def submit_event(self, event: SafetyEvent) -> None:
        self._events.put(event)

    def _run(self) -> None:
        while not self._stop.is_set() or not self._frames.empty() or not self._events.empty():
            self._drain_events()
            try:
                frame = self._frames.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._handle_frame(frame)
            finally:
                self._frames.task_done()
        self._drain_events()
        for pending in list(self._pending_falls):
            try:
                self._finalize_fall(pending)
            except Exception:
                log.exception("Could not finalize fall evidence %s", pending.event.event_id)

    def _drain_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            try:
                self._handle_event(event)
            except Exception:
                log.exception("Could not capture evidence for event %s", event.event_id)
            finally:
                self._events.task_done()

    def _handle_frame(self, frame: _FrameInput) -> None:
        ok, encoded = cv2.imencode(
            ".jpg", frame.frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        )
        if not ok:
            return
        sample = _FrameSample(frame.captured_at, encoded.tobytes(), frame.bboxes)
        self._ring.append(sample)
        cutoff = frame.captured_at - self.pre_seconds
        while self._ring and self._ring[0].captured_at < cutoff:
            self._ring.popleft()
        for pending in list(self._pending_falls):
            if sample.captured_at <= pending.deadline:
                pending.samples.append(sample)
            if sample.captured_at >= pending.deadline:
                self._finalize_fall(pending)

    def _handle_event(self, event: SafetyEvent) -> None:
        if not self._ring:
            raise RuntimeError("no sampled frame available")
        sample = min(self._ring, key=lambda item: abs(item.captured_at - event.detected_at))
        image_path = self.spool_dir / f"{event.event_id}_image.jpg"
        image_path.write_bytes(self._annotated_jpeg(sample, event))
        if isinstance(event, FallDetectedEvent):
            pre_samples = [
                item
                for item in self._ring
                if event.detected_at - self.pre_seconds <= item.captured_at
            ]
            self._pending_falls.append(
                _PendingFall(
                    event=event,
                    image_path=image_path,
                    samples=pre_samples,
                    deadline=event.detected_at + self.post_seconds,
                )
            )
            return
        self.submit_job(
            EvidenceJob(
                event.event_id,
                (EvidenceFile("IMAGE", "image/jpeg", image_path),),
            )
        )

    def _annotated_jpeg(self, sample: _FrameSample, event: SafetyEvent) -> bytes:
        frame = cv2.imdecode(np.frombuffer(sample.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self._draw_event(frame, sample.bboxes.get(event.track_id), event)
        ok, encoded = cv2.imencode(
            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        )
        if not ok:
            raise RuntimeError("could not encode annotated evidence image")
        return encoded.tobytes()

    @staticmethod
    def _draw_event(frame: np.ndarray, bbox: np.ndarray | None, event: SafetyEvent) -> None:
        color = (0, 0, 255) if isinstance(event, FallDetectedEvent) else (0, 140, 255)
        if bbox is not None:
            x1, y1, x2, y2 = np.asarray(bbox, dtype=int)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 4)
            origin = (x1, max(25, y1 - 8))
        else:
            origin = (12, 30)
        label = f"{event.violation_type.value} {event.track_id}"
        cv2.putText(
            frame,
            label[:80],
            origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
            cv2.LINE_AA,
        )

    def _finalize_fall(self, pending: _PendingFall) -> None:
        if pending not in self._pending_falls:
            return
        self._pending_falls.remove(pending)
        if not pending.samples:
            raise RuntimeError("fall clip has no frames")
        video_path = self.spool_dir / f"{pending.event.event_id}_video.mp4"
        first = cv2.imdecode(
            np.frombuffer(pending.samples[0].jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        if first is None:
            raise RuntimeError("could not decode first fall evidence frame")
        height, width = first.shape[:2]
        temporary_path = video_path.with_name(f"{video_path.stem}.encoding.mp4")
        temporary_path.unlink(missing_ok=True)

        try:
            import imageio_ffmpeg
        except ImportError as exc:
            raise RuntimeError(
                "imageio-ffmpeg is required to create browser-compatible evidence"
            ) from exc

        command = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(self.sample_fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(temporary_path),
        ]
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            for sample in pending.samples:
                frame = cv2.imdecode(
                    np.frombuffer(sample.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
                )
                if frame is None:
                    raise RuntimeError("could not decode fall evidence frame")
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
                self._draw_event(
                    frame, sample.bboxes.get(pending.event.track_id), pending.event
                )
                if process.stdin is None:
                    raise RuntimeError("FFmpeg input pipe is unavailable")
                process.stdin.write(np.ascontiguousarray(frame).tobytes())
            if process.stdin is not None:
                process.stdin.close()
            stderr = process.stderr.read() if process.stderr is not None else b""
            return_code = process.wait()
            if return_code != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"FFmpeg H.264 encoding failed: {detail[-1000:]}")
            if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg produced an empty fall evidence video")
            temporary_path.replace(video_path)
        except Exception:
            if process.poll() is None:
                process.kill()
            process.wait()
            temporary_path.unlink(missing_ok=True)
            video_path.unlink(missing_ok=True)
            raise
        self.submit_job(
            EvidenceJob(
                pending.event.event_id,
                (
                    EvidenceFile("IMAGE", "image/jpeg", pending.image_path),
                    EvidenceFile("VIDEO", "video/mp4", video_path),
                ),
            )
        )

    def close(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while (self._frames.unfinished_tasks or self._events.unfinished_tasks) and time.monotonic() < deadline:
            time.sleep(0.05)
        self._stop.set()
        self._thread.join(timeout=max(1.0, timeout))

    def stats(self) -> dict[str, int]:
        return {
            "dropped_frames": self.dropped_frames,
            "ring_frames": len(self._ring),
            "pending_falls": len(self._pending_falls),
        }
