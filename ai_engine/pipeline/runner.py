"""Standalone multi-process Layer 0-2 visual and backend integration test."""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import time
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
    frame, tracked, metrics: Layer1MetricsSnapshot, overlay_store: OverlayStateStore
) -> None:
    draw_tracking_overlay(frame, tracked, metrics, overlay_store)


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

    layer2 = Layer2Runtime(
        CameraLayer2Config(
            camera_id=config.camera_id,
            camera_key=config.camera_key,
            models=options.layer2_models,
            triton_url=options.triton_url,
        ),
        on_event=on_layer2_event,
        on_track_update=on_track_update,
    )
    layer2.start()
    stale_drops = 0
    ingest.start()
    started = time.monotonic()
    try:
        while not stop_event.is_set():
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
            if evidence_capture is not None:
                evidence_capture.observe(tracked)
            layer2.dispatch(tracked)
            if options.show:
                visual = tracked.frame_bgr.copy()
                draw_overlay(visual, tracked, metrics, overlay_store)
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
