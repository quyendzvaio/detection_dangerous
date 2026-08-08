"""Standalone multi-process Layer 0-2 visual and backend integration test."""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable

import cv2

from ai_engine.contracts.event_schema import CameraStatus, CameraStatusEvent
from ai_engine.events import EventBus, HttpEventTransport
from ai_engine.evidence import EvidenceCapture, EvidenceUploader
from ai_engine.inference.pose_client import PoseClient
from ai_engine.ingest.camera_stream import CameraConfig, CameraIngest
from ai_engine.ingest.layer0_multi_runner import parse_camera_spec
from ai_engine.pipeline.layer1_processor import Layer1MetricsSnapshot, Layer1Processor
from ai_engine.pipeline.layer2_runtime import (
    CameraLayer2Config,
    Layer2Runtime,
    ModelToggles,
)
from ai_engine.tracking.botsort_adapter import BotSortAdapter
from ai_engine.visualization.track_overlay import OverlayStateStore, draw_tracking_overlay


@dataclass(frozen=True)
class DemoOptions:
    triton_url: str
    confidence: float
    iou: float
    max_frame_age_ms: float
    duration: float
    show: bool
    layer2_models: ModelToggles
    backend_event_url: str | None
    ai_service_token: str | None
    event_buffer_size: int
    evidence_enabled: bool
    evidence_spool_dir: str
    evidence_sample_fps: float
    evidence_pre_seconds: float
    evidence_post_seconds: float
    runtime_config_poll_seconds: float
    preview_fps: float


class RuntimeConfigClient:
    def __init__(self, event_url: str, service_token: str, camera_id: int) -> None:
        import requests

        internal_base = event_url.rsplit("/", 1)[0]
        self.config_url = f"{internal_base}/cameras/{camera_id}/runtime-config"
        self.ack_url = f"{self.config_url}/ack"
        self.telemetry_url = f"{internal_base}/cameras/{camera_id}/telemetry"
        self.frame_url = f"{internal_base}/cameras/{camera_id}/frame"
        self.headers = {"Authorization": f"Bearer {service_token}"}
        self.session = requests.Session()
        self.frame_session = requests.Session()
        self.frame_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="frame-publish"
        )
        self.frame_future: Future | None = None
        self.applied_revision: int | None = None

    def poll_and_apply(self, runtime: Layer2Runtime, timeout: float = 3.0) -> bool:
        response = self.session.get(self.config_url, headers=self.headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        revision = int(payload["revision"])
        if revision == self.applied_revision:
            return False
        models = {
            "zone": bool(payload["zone_enabled"]),
            "fall": bool(payload["fall_enabled"]),
            "ppe": bool(payload["ppe_enabled"]),
        }
        try:
            runtime.set_models(**models)
            runtime.set_zones(payload.get("zones", []))
            ack_payload = {
                "revision": revision,
                "status": "APPLIED",
                "zone_enabled": models["zone"],
                "fall_enabled": models["fall"],
                "ppe_enabled": models["ppe"],
            }
        except Exception as exc:
            ack_payload = {
                "revision": revision,
                "status": "FAILED",
                "zone_enabled": models["zone"],
                "fall_enabled": models["fall"],
                "ppe_enabled": models["ppe"],
                "error": str(exc)[:1000],
            }
        ack = self.session.post(
            self.ack_url, json=ack_payload, headers=self.headers, timeout=timeout
        )
        ack.raise_for_status()
        if ack_payload["status"] == "FAILED":
            raise RuntimeError(ack_payload["error"])
        self.applied_revision = revision
        return True

    def close(self) -> None:
        self.frame_executor.shutdown(wait=True, cancel_futures=True)
        self.frame_session.close()
        self.session.close()

    def publish_telemetry(
        self, metrics: Layer1MetricsSnapshot, last_frame_at: float, timeout: float = 3.0
    ) -> None:
        response = self.session.post(
            self.telemetry_url,
            json={
                "processing_fps": metrics.processing_fps,
                "latency_ms": metrics.end_to_end_ms,
                "last_frame_at": datetime.fromtimestamp(
                    last_frame_at, timezone.utc
                ).isoformat(),
            },
            headers=self.headers,
            timeout=timeout,
        )
        response.raise_for_status()

    def _publish_frame(self, frame, overlay: bool, timeout: float = 3.0) -> None:
        encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 78])
        if not encoded:
            raise RuntimeError("JPEG encoding failed")
        response = self.frame_session.post(
            self.frame_url,
            params={"overlay": str(overlay).lower()},
            data=jpeg.tobytes(),
            headers={**self.headers, "Content-Type": "image/jpeg"},
            timeout=timeout,
        )
        response.raise_for_status()

    def submit_frames(self, raw_frame, annotated_frame) -> bool:
        """Drop a preview update while the previous one is still uploading."""
        if self.frame_future is not None and not self.frame_future.done():
            return False
        if self.frame_future is not None:
            self.frame_future.result()
        self.frame_future = self.frame_executor.submit(
            self._publish_frame_pair, raw_frame.copy(), annotated_frame.copy()
        )
        return True

    def _publish_frame_pair(self, raw_frame, annotated_frame) -> None:
        self._publish_frame(raw_frame, overlay=False)
        self._publish_frame(annotated_frame, overlay=True)


def parse_layer2_models(raw: str) -> ModelToggles:
    names = {item.strip().lower() for item in raw.split(",") if item.strip()}
    allowed = {"zone", "fall", "ppe"}
    unknown = names - allowed
    if unknown:
        raise argparse.ArgumentTypeError(
            f"Unknown Layer 2 model(s): {sorted(unknown)}; allowed: zone, fall, ppe"
        )
    return ModelToggles(**{name: name in names for name in allowed})


def draw_overlay(
    frame,
    tracked,
    metrics: Layer1MetricsSnapshot,
    overlay_store: OverlayStateStore,
    zones=(),
) -> None:
    draw_tracking_overlay(frame, tracked, metrics, overlay_store, zones=zones)


def register_runtime_cameras(
    cameras: list[CameraConfig], options: DemoOptions, timeout: float = 5.0
) -> None:
    """Create/update DB camera rows before child processes begin sending events."""
    if options.backend_event_url is None:
        return

    import requests

    internal_base = options.backend_event_url.rsplit("/", 1)[0]
    headers = {"Authorization": f"Bearer {options.ai_service_token}"}
    for camera in cameras:
        response = requests.put(
            f"{internal_base}/cameras/{camera.camera_id}",
            json={
                "camera_key": camera.camera_key,
                "name": camera.camera_key,
                "source": str(camera.source),
                "zone_enabled": options.layer2_models.zone,
                "fall_enabled": options.layer2_models.fall,
                "ppe_enabled": options.layer2_models.ppe,
            },
            headers=headers,
            timeout=timeout,
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Camera {camera.camera_key} registration failed: "
                f"HTTP {response.status_code} {response.text[:500]}"
            )
        action = "created" if response.status_code == 201 else "updated"
        print(f"[pipeline:{camera.camera_key}] backend camera {action}", flush=True)


def run_camera_process(
    config: CameraConfig, options: DemoOptions, stop_event: mp.synchronize.Event
) -> None:
    prefix = f"[pipeline:{config.camera_key}]"
    event_bus = None
    if options.backend_event_url is not None:
        event_bus = EventBus(
            HttpEventTransport(
                event_url=options.backend_event_url,
                service_token=options.ai_service_token,
            ),
            max_buffer=options.event_buffer_size,
        )

    evidence_uploader = None
    evidence_capture = None
    if options.evidence_enabled:
        if options.backend_event_url is None or not options.ai_service_token:
            raise RuntimeError("Evidence upload requires backend URL and AI service token")
        camera_spool = Path(options.evidence_spool_dir)
        evidence_uploader = EvidenceUploader(
            options.backend_event_url,
            options.ai_service_token,
            camera_spool / config.camera_key,
        )
        evidence_capture = EvidenceCapture(
            config.camera_key,
            camera_spool,
            evidence_uploader.submit,
            sample_fps=options.evidence_sample_fps,
            pre_seconds=options.evidence_pre_seconds,
            post_seconds=options.evidence_post_seconds,
        )

    last_camera_status: CameraStatus | None = None

    def publish_camera_status(raw_status: str, message: str) -> None:
        nonlocal last_camera_status
        mapped = {
            "ONLINE": CameraStatus.ONLINE,
            "OFFLINE": CameraStatus.OFFLINE,
            "EOF": CameraStatus.OFFLINE,
        }.get(raw_status)
        if event_bus is None or mapped is None:
            return
        if mapped == last_camera_status:
            return
        last_camera_status = mapped
        event_bus.publish(
            CameraStatusEvent(
                camera_id=config.camera_id,
                status=mapped,
                observed_at=time.time(),
                reason=message,
                source="CAMERA_PROCESS",
            )
        )

    def on_ingest_status(status: str, message: str) -> None:
        print(f"{prefix} {status}: {message}", flush=True)
        publish_camera_status(status, message)

    ingest = CameraIngest(config, status_callback=on_ingest_status)
    pose = PoseClient(
        url=options.triton_url,
        conf_thresh=options.confidence,
        iou_thresh=options.iou,
    )
    tracker = BotSortAdapter(frame_rate=config.fps)
    processor = Layer1Processor(config.camera_key, pose, tracker)
    overlay_store = OverlayStateStore()

    def on_layer2_event(event) -> None:
        overlay_store.apply_event(event)
        if event_bus is not None:
            event_bus.publish(event)
        if evidence_capture is not None:
            evidence_capture.submit_event(event)
        print(
            f"{prefix} {event.violation_type.value} "
            f"track={event.track_id} payload={event.to_backend_payload()}",
            flush=True,
        )

    def on_track_update(update) -> None:
        overlay_store.apply_update(update)

    def on_models_changed(previous: ModelToggles, current: ModelToggles) -> None:
        for branch in Layer2Runtime.BRANCHES:
            if getattr(previous, branch) and not getattr(current, branch):
                overlay_store.clear_branch(branch)

    layer2 = Layer2Runtime(
        CameraLayer2Config(
            camera_id=config.camera_id,
            camera_key=config.camera_key,
            models=options.layer2_models,
            triton_url=options.triton_url,
        ),
        on_event=on_layer2_event,
        on_track_update=on_track_update,
        on_models_changed=on_models_changed,
    )
    layer2.start()
    runtime_config = None
    if options.backend_event_url is not None and options.ai_service_token:
        runtime_config = RuntimeConfigClient(
            options.backend_event_url, options.ai_service_token, config.camera_id
        )
        try:
            runtime_config.poll_and_apply(layer2)
        except Exception as exc:
            print(f"{prefix} RUNTIME_CONFIG_ERROR: {exc}", flush=True)
    next_config_poll = time.monotonic() + options.runtime_config_poll_seconds
    next_telemetry_publish = time.monotonic() + 2.0
    next_frame_publish = time.monotonic()
    stale_drops = 0
    ingest.start()
    started = time.monotonic()
    try:
        while not stop_event.is_set():
            now = time.monotonic()
            if runtime_config is not None and now >= next_config_poll:
                try:
                    if runtime_config.poll_and_apply(layer2):
                        print(f"{prefix} runtime config applied", flush=True)
                except Exception as exc:
                    print(f"{prefix} RUNTIME_CONFIG_ERROR: {exc}", flush=True)
                next_config_poll = now + options.runtime_config_poll_seconds
            captured = ingest.buffer.take_latest(timeout=0.5)
            if captured is None:
                if not ingest.is_alive():
                    break
                continue
            frame_age_ms = (time.time() - captured.captured_at) * 1000
            if frame_age_ms > options.max_frame_age_ms:
                stale_drops += 1
                continue
            try:
                tracked, metrics = processor.process(captured)
            except Exception as exc:
                print(f"{prefix} POSE_OR_TRACKER_ERROR: {exc}", flush=True)
                time.sleep(0.2)
                continue
            if runtime_config is not None and time.monotonic() >= next_telemetry_publish:
                try:
                    runtime_config.publish_telemetry(metrics, captured.captured_at)
                except Exception as exc:
                    print(f"{prefix} TELEMETRY_ERROR: {exc}", flush=True)
                next_telemetry_publish = time.monotonic() + 2.0
            if evidence_capture is not None:
                evidence_capture.observe(tracked)
            layer2.dispatch(tracked)
            if runtime_config is not None and time.monotonic() >= next_frame_publish:
                try:
                    annotated = tracked.frame_bgr.copy()
                    visible_zones = layer2.zones() if layer2.models().zone else ()
                    draw_overlay(annotated, tracked, metrics, overlay_store, visible_zones)
                    runtime_config.submit_frames(tracked.frame_bgr, annotated)
                except Exception as exc:
                    print(f"{prefix} FRAME_PUBLISH_ERROR: {exc}", flush=True)
                next_frame_publish = time.monotonic() + (1.0 / options.preview_fps)
            if options.show:
                visual = tracked.frame_bgr.copy()
                visible_zones = layer2.zones() if layer2.models().zone else ()
                draw_overlay(visual, tracked, metrics, overlay_store, visible_zones)
                cv2.putText(
                    visual,
                    f"stale drops: {stale_drops}",
                    (12, visual.shape[0] - 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (0, 100, 255),
                    2,
                )
                cv2.imshow(f"Pipeline [{config.camera_key}]", visual)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop_event.set()
                    break
            if options.duration and time.monotonic() - started >= options.duration:
                break
    finally:
        ingest.stop()
        publish_camera_status("OFFLINE", "Camera process stopped")
        layer2.close()
        if evidence_capture is not None:
            evidence_capture.close(timeout=12.0)
            print(f"{prefix} evidence_capture={evidence_capture.stats()}", flush=True)
        if options.show:
            cv2.destroyAllWindows()
        print(f"{prefix} layer2={layer2.metrics()}", flush=True)
        snapshot = processor.metrics.snapshot(0)
        print(
            f"{prefix} stopped: fps={snapshot.processing_fps:.1f}, "
            f"pose={snapshot.pose_ms:.1f}ms, tracker={snapshot.tracker_ms:.1f}ms, "
            f"e2e={snapshot.end_to_end_ms:.1f}ms, stale_drops={stale_drops}",
            flush=True,
        )
        if event_bus is not None:
            event_bus.close(timeout=5.0)
            print(f"{prefix} event_bus={event_bus.stats()}", flush=True)
        if runtime_config is not None:
            runtime_config.close()
        if evidence_uploader is not None:
            evidence_uploader.close(timeout=20.0)
            print(f"{prefix} evidence_uploader={evidence_uploader.stats()}", flush=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run standalone multi-camera Layer 0-2 visual test"
    )
    parser.add_argument(
        "--camera",
        action="append",
        required=True,
        type=parse_camera_spec,
        metavar="ID:KEY:SOURCE",
    )
    parser.add_argument("--triton-url", default="localhost:8001")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--max-frame-age-ms", type=float, default=250)
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--show", action="store_true", help="show compact bbox/ID/alerts and latency")
    parser.add_argument(
        "--layer2-models",
        type=parse_layer2_models,
        default=parse_layer2_models("zone,fall"),
        metavar="MODELS",
        help="comma-separated: zone,fall,ppe (Re-ID is outside this phase)",
    )
    parser.add_argument(
        "--backend-event-url",
        default=os.getenv("BACKEND_EVENT_URL") or None,
        help="enable backend publishing, e.g. http://localhost:8080/api/v1/internal/events",
    )
    parser.add_argument(
        "--ai-service-token",
        default=os.getenv("AI_SERVICE_TOKEN") or None,
        help="Bearer token for internal backend endpoints",
    )
    parser.add_argument("--event-buffer-size", type=int, default=200)
    parser.add_argument(
        "--runtime-config-poll-seconds",
        type=float,
        default=float(os.getenv("RUNTIME_CONFIG_POLL_SECONDS", "1")),
    )
    parser.add_argument(
        "--preview-fps",
        type=float,
        default=float(os.getenv("WEB_PREVIEW_FPS", "10")),
        help="maximum browser preview frame rate",
    )
    parser.add_argument(
        "--evidence",
        action="store_true",
        default=os.getenv("EVIDENCE_ENABLED", "0").lower() in {"1", "true", "yes"},
        help="capture evidence and upload directly to object storage using backend-signed URLs",
    )
    parser.add_argument(
        "--evidence-spool-dir",
        default=os.getenv("EVIDENCE_SPOOL_DIR", "evidence_spool"),
    )
    parser.add_argument("--evidence-sample-fps", type=float, default=8.0)
    parser.add_argument("--evidence-pre-seconds", type=float, default=5.0)
    parser.add_argument("--evidence-post-seconds", type=float, default=5.0)
    parser.add_argument(
        "--skip-camera-registration",
        action="store_true",
        help="require camera rows to already exist in the backend",
    )
    args = parser.parse_args(argv)
    if len({camera.camera_id for camera in args.camera}) != len(args.camera):
        parser.error("Camera IDs must be unique")
    if len({camera.camera_key for camera in args.camera}) != len(args.camera):
        parser.error("Camera keys must be unique")
    if args.backend_event_url and not args.ai_service_token:
        parser.error("--ai-service-token is required when backend publishing is enabled")
    if args.event_buffer_size <= 0:
        parser.error("--event-buffer-size must be positive")
    if args.runtime_config_poll_seconds <= 0:
        parser.error("--runtime-config-poll-seconds must be positive")
    if not 0 < args.preview_fps <= 30:
        parser.error("--preview-fps must be between 0 and 30")
    if args.evidence and not args.backend_event_url:
        parser.error("--evidence requires --backend-event-url")
    if min(
        args.evidence_sample_fps,
        args.evidence_pre_seconds,
        args.evidence_post_seconds,
    ) <= 0:
        parser.error("evidence fps/pre/post values must be positive")

    options = DemoOptions(
        args.triton_url,
        args.confidence,
        args.iou,
        args.max_frame_age_ms,
        args.duration,
        args.show,
        args.layer2_models,
        args.backend_event_url,
        args.ai_service_token,
        args.event_buffer_size,
        args.evidence,
        args.evidence_spool_dir,
        args.evidence_sample_fps,
        args.evidence_pre_seconds,
        args.evidence_post_seconds,
        args.runtime_config_poll_seconds,
        args.preview_fps,
    )
    if options.backend_event_url and not args.skip_camera_registration:
        register_runtime_cameras(args.camera, options)

    context = mp.get_context("spawn")
    stop_event = context.Event()
    processes = [
        context.Process(
            target=run_camera_process,
            args=(camera, options, stop_event),
            name=f"pipeline-{camera.camera_key}",
        )
        for camera in args.camera
    ]
    for process in processes:
        process.start()
    try:
        while any(process.is_alive() for process in processes):
            time.sleep(0.2)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        for process in processes:
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
    return 0 if all(process.exitcode in (0, None) for process in processes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
