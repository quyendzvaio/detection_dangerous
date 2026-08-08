"""A one-slot mailbox that always retains the newest captured frame."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from ai_engine.contracts.event_schema import CapturedFrame


@dataclass(frozen=True)
class LatestFrameStats:
    accepted: int
    overwritten: int
    delivered: int
    pending: bool
    closed: bool


class LatestFrameBuffer:
    """Thread-safe single-slot buffer.

    Publishing a frame never waits for a slow consumer. If the slot still holds
    an unread frame, that old frame is replaced and counted as overwritten.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._latest: Optional[CapturedFrame] = None
        self._closed = False
        self._accepted = 0
        self._overwritten = 0
        self._delivered = 0

    def publish(self, frame: CapturedFrame) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("Cannot publish to a closed LatestFrameBuffer")
            if self._latest is not None:
                self._overwritten += 1
            self._latest = frame
            self._accepted += 1
            self._condition.notify()

    def take_latest(self, timeout: Optional[float] = None) -> Optional[CapturedFrame]:
        """Return the newest available frame, or None on timeout/closed buffer."""
        with self._condition:
            if timeout is None:
                while self._latest is None and not self._closed:
                    self._condition.wait()
            else:
                deadline = time.monotonic() + max(0.0, timeout)
                while self._latest is None and not self._closed:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._condition.wait(remaining)
            if self._latest is None:
                return None
            frame = self._latest
            self._latest = None
            self._delivered += 1
            return frame

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()

    def stats(self) -> LatestFrameStats:
        with self._condition:
            return LatestFrameStats(
                accepted=self._accepted,
                overwritten=self._overwritten,
                delivered=self._delivered,
                pending=self._latest is not None,
                closed=self._closed,
            )
