"""Standalone multi-process Layer 0-2 visual test."""
from __future__ import annotations

import argparse
import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Iterable

import cv2

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


def run_camera_process(
    config: CameraConfig, options: DemoOptions, stop_event: mp.synchronize.Event
) -> None:
    prefix = f"[pipeline:{config.camera_key}]"
    ingest = CameraIngest(
        config,
        status_callback=lambda status, message: print(
            f"{prefix} {status}: {message}", flush=True
        ),
    )
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
        layer2.close()
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
    args = parser.parse_args(argv)
    if len({camera.camera_id for camera in args.camera}) != len(args.camera):
        parser.error("Camera IDs must be unique")
    if len({camera.camera_key for camera in args.camera}) != len(args.camera):
        parser.error("Camera keys must be unique")

    context = mp.get_context("spawn")
    stop_event = context.Event()
    options = DemoOptions(
        args.triton_url,
        args.confidence,
        args.iou,
        args.max_frame_age_ms,
        args.duration,
        args.show,
        args.layer2_models,
    )
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
