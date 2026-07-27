"""Launch one independent Layer 0 process for each configured camera."""

from __future__ import annotations

import argparse
import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Iterable

import cv2

from ai_engine.ingest.camera_stream import CameraConfig, CameraIngest


@dataclass(frozen=True)
class RunnerOptions:
    duration: float
    consumer_delay_ms: float
    show: bool


def parse_source(raw: str) -> str | int:
    return int(raw) if raw.isdigit() else raw


def parse_camera_spec(raw: str) -> CameraConfig:
    """Parse ID:KEY:SOURCE while preserving colons inside RTSP/HTTP URLs."""
    parts = raw.split(":", 2)
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        raise argparse.ArgumentTypeError(
            "Camera must use ID:KEY:SOURCE, e.g. 1:cam1:0 or 2:cam2:rtsp://host/stream"
        )
    try:
        camera_id = int(parts[0])
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Camera ID must be an integer") from exc
    return CameraConfig(camera_id=camera_id, camera_key=parts[1], source=parse_source(parts[2]))


def run_camera_process(config: CameraConfig, options: RunnerOptions, stop_event: mp.synchronize.Event) -> None:
    """Child-process target. It owns its OpenCV handle, thread and frame buffer."""
    prefix = f"[layer0:{config.camera_key}]"
    ingest = CameraIngest(config, status_callback=lambda status, message: print(f"{prefix} {status}: {message}", flush=True))
    ingest.start()
    started = time.monotonic()
    next_report = started + 1.0
    received = 0
    try:
        while not stop_event.is_set():
            frame = ingest.buffer.take_latest(timeout=0.5)
            if frame is not None:
                received += 1
                age_ms = (time.time() - frame.captured_at) * 1000
                if options.show:
                    cv2.putText(
                        frame.frame_bgr,
                        f"{config.camera_key} seq={frame.sequence_id} age={age_ms:.0f}ms",
                        (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 255),
                        2,
                    )
                    cv2.imshow(f"Layer 0 [{config.camera_key}]", frame.frame_bgr)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        stop_event.set()
                        break
                if options.consumer_delay_ms:
                    time.sleep(options.consumer_delay_ms / 1000)
            elif not ingest.is_alive():
                break
            now = time.monotonic()
            if now >= next_report:
                stats = ingest.buffer.stats()
                print(
                    f"{prefix} received={received} accepted={stats.accepted} "
                    f"overwritten={stats.overwritten} delivered={stats.delivered} "
                    f"reconnects={ingest.reconnect_count}",
                    flush=True,
                )
                next_report = now + 1.0
            if options.duration and now - started >= options.duration:
                break
    finally:
        ingest.stop()
        if options.show:
            cv2.destroyAllWindows()
        stats = ingest.buffer.stats()
        print(f"{prefix} stopped: accepted={stats.accepted}, overwritten={stats.overwritten}, delivered={stats.delivered}", flush=True)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one isolated Layer 0 process per camera")
    parser.add_argument(
        "--camera",
        action="append",
        required=True,
        type=parse_camera_spec,
        metavar="ID:KEY:SOURCE",
        help="repeat once per camera; source may be a USB index, file path, RTSP or HTTP URL",
    )
    parser.add_argument("--duration", type=float, default=0, help="seconds; 0 means until q/Ctrl-C or all file sources end")
    parser.add_argument("--consumer-delay-ms", type=float, default=0, help="simulate a slow next layer in every child")
    parser.add_argument("--show", action="store_true", help="show one window per camera; press q in any window to stop all")
    args = parser.parse_args(argv)
    camera_ids = [config.camera_id for config in args.camera]
    camera_keys = [config.camera_key for config in args.camera]
    if len(camera_ids) != len(set(camera_ids)) or len(camera_keys) != len(set(camera_keys)):
        parser.error("Each --camera needs a unique camera ID and camera key")

    context = mp.get_context("spawn")
    stop_event = context.Event()
    options = RunnerOptions(args.duration, args.consumer_delay_ms, args.show)
    processes = [
        context.Process(
            target=run_camera_process,
            args=(config, options, stop_event),
            name=f"layer0-{config.camera_key}",
        )
        for config in args.camera
    ]
    for process in processes:
        process.start()
    try:
        while any(process.is_alive() for process in processes):
            if args.duration:
                time.sleep(args.duration)
                stop_event.set()
                break
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
