"""Standalone Layer 0 test runner; does not require Triton or BoxMOT."""

from __future__ import annotations

import argparse
import time

import cv2

from ai_engine.ingest.camera_stream import CameraConfig, CameraIngest


def parse_source(raw: str) -> str | int:
    return int(raw) if raw.isdigit() else raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and observe Layer 0 camera ingest only")
    parser.add_argument("--source", default="0", help="USB index, video file, RTSP, or HTTP source")
    parser.add_argument("--camera-id", type=int, default=1)
    parser.add_argument("--camera-key", default="cam1")
    parser.add_argument("--duration", type=float, default=0, help="seconds; 0 means until q/Ctrl-C or EOF")
    parser.add_argument("--consumer-delay-ms", type=float, default=0, help="simulate a slow next layer")
    parser.add_argument("--show", action="store_true", help="show raw frames; press q to stop")
    args = parser.parse_args()

    config = CameraConfig(
        camera_id=args.camera_id,
        camera_key=args.camera_key,
        source=parse_source(args.source),
    )
    ingest = CameraIngest(
        config,
        status_callback=lambda status, message: print(f"[layer0] {status}: {message}"),
    )
    ingest.start()
    started = time.monotonic()
    next_report = started + 1.0
    received = 0
    try:
        while True:
            frame = ingest.buffer.take_latest(timeout=0.5)
            if frame is not None:
                received += 1
                age_ms = (time.time() - frame.captured_at) * 1000
                if args.show:
                    cv2.putText(
                        frame.frame_bgr,
                        f"age={age_ms:.0f}ms",
                        (12, 28),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 255),
                        2,
                    )
                    cv2.imshow(f"Layer 0 [{frame.camera_key}]", frame.frame_bgr)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                if args.consumer_delay_ms:
                    time.sleep(args.consumer_delay_ms / 1000)
            elif not ingest.is_alive():
                break
            now = time.monotonic()
            if now >= next_report:
                stats = ingest.buffer.stats()
                print(
                    f"[layer0] received={received} accepted={stats.accepted} "
                    f"overwritten={stats.overwritten} delivered={stats.delivered} "
                    f"reconnects={ingest.reconnect_count}"
                )
                next_report = now + 1.0
            if args.duration and now - started >= args.duration:
                break
    except KeyboardInterrupt:
        pass
    finally:
        ingest.stop()
        if args.show:
            cv2.destroyAllWindows()
    stats = ingest.buffer.stats()
    print(f"[layer0] stopped: accepted={stats.accepted}, overwritten={stats.overwritten}, delivered={stats.delivered}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
