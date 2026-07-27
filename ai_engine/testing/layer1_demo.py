"""Standalone multi-process Layer 1 visual test; no Layer 2 integration."""

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
from ai_engine.tracking.botsort_adapter import BotSortAdapter

_SKELETON = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]


@dataclass(frozen=True)
class DemoOptions:
    triton_url: str
    confidence: float
    iou: float
    max_frame_age_ms: float
    duration: float
    show: bool


def draw_overlay(frame, tracked, metrics: Layer1MetricsSnapshot) -> None:
    for person in tracked.persons:
        x1, y1, x2, y2 = person.bbox_xyxy.astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, person.track_id, (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        for start, end in _SKELETON:
            points = person.keypoints
            if points[start, 2] >= 0.3 and points[end, 2] >= 0.3:
                cv2.line(frame, tuple(points[start, :2].astype(int)), tuple(points[end, :2].astype(int)), (255, 180, 0), 2)
    lines = [
        f"FPS: {metrics.processing_fps:.1f}",
        f"Pose: {metrics.pose_ms:.1f} ms",
        f"Tracker: {metrics.tracker_ms:.1f} ms",
        f"E2E: {metrics.end_to_end_ms:.1f} ms",
        f"Tracks: {metrics.active_tracks}",
    ]
    for index, line in enumerate(lines):
        cv2.putText(frame, line, (12, 28 + index * 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 2)


def run_camera_process(config: CameraConfig, options: DemoOptions, stop_event: mp.synchronize.Event) -> None:
    prefix = f"[layer1:{config.camera_key}]"
    ingest = CameraIngest(config, status_callback=lambda status, message: print(f"{prefix} {status}: {message}", flush=True))
    pose = PoseClient(url=options.triton_url, conf_thresh=options.confidence, iou_thresh=options.iou)
    tracker = BotSortAdapter(frame_rate=config.fps)
    processor = Layer1Processor(config.camera_key, pose, tracker)
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
            if options.show:
                visual = tracked.frame_bgr.copy()
                draw_overlay(visual, tracked, metrics)
                cv2.putText(visual, f"stale drops: {stale_drops}", (12, visual.shape[0] - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 100, 255), 2)
                cv2.imshow(f"Layer 1 [{config.camera_key}]", visual)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    stop_event.set()
                    break
            if options.duration and time.monotonic() - started >= options.duration:
                break
    finally:
        ingest.stop()
        if options.show:
            cv2.destroyAllWindows()
        snapshot = processor.metrics.snapshot(0)
        print(f"{prefix} stopped: fps={snapshot.processing_fps:.1f}, pose={snapshot.pose_ms:.1f}ms, tracker={snapshot.tracker_ms:.1f}ms, e2e={snapshot.end_to_end_ms:.1f}ms, stale_drops={stale_drops}", flush=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run standalone Layer 1 Pose + BoT-SORT visual test")
    parser.add_argument("--camera", action="append", required=True, type=parse_camera_spec, metavar="ID:KEY:SOURCE")
    parser.add_argument("--triton-url", default="localhost:8001")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--iou", type=float, default=0.45)
    parser.add_argument("--max-frame-age-ms", type=float, default=250)
    parser.add_argument("--duration", type=float, default=0)
    parser.add_argument("--show", action="store_true", help="show bbox, ID, skeleton and latency overlay")
    args = parser.parse_args(argv)
    if len({camera.camera_id for camera in args.camera}) != len(args.camera):
        parser.error("Camera IDs must be unique")
    if len({camera.camera_key for camera in args.camera}) != len(args.camera):
        parser.error("Camera keys must be unique")
    context = mp.get_context("spawn")
    stop_event = context.Event()
    options = DemoOptions(args.triton_url, args.confidence, args.iou, args.max_frame_age_ms, args.duration, args.show)
    processes = [context.Process(target=run_camera_process, args=(camera, options, stop_event), name=f"layer1-{camera.camera_key}") for camera in args.camera]
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
