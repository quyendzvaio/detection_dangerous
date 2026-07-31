"""Non-blocking transport for typed domain events."""
from __future__ import annotations

import logging
import queue
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable

from ai_engine.contracts.event_schema import DomainEvent, SafetyEvent, Severity

log = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    pass


class EventTransport(ABC):
    """Blocking transport interface; EventBus calls it only from its sender thread."""

    @abstractmethod
    def send(self, event: DomainEvent) -> None:
        raise NotImplementedError


class HttpEventTransport(EventTransport):
    def __init__(
        self,
        url: str = "http://localhost:8080/api/v1/internal/events",
        timeout: float = 3.0,
        retries: int = 2,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def send(self, event: DomainEvent) -> None:
        session = self._get_session()
        body = event.to_backend_payload()
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = session.post(self.url, json=body, timeout=self.timeout)
                response.raise_for_status()
                return
            except Exception as exc:
                last_error = exc
                log.warning(
                    "Event %s delivery failed on attempt %d: %s",
                    event.event_id,
                    attempt + 1,
                    exc,
                )
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
        raise DeliveryError(
            f"event {event.event_id} failed after {self.retries + 1} attempts"
        ) from last_error


class InProcessTransport(EventTransport):
    def __init__(self, sink: Callable[[DomainEvent], None] | list[DomainEvent]) -> None:
        self.sink = sink

    def send(self, event: DomainEvent) -> None:
        if callable(self.sink):
            self.sink(event)
        else:
            self.sink.append(event)


class EventBus:
    """Bounded producer/consumer bridge that never blocks a camera frame loop."""

    def __init__(self, transport: EventTransport, max_buffer: int = 200) -> None:
        self.transport = transport
        self._buffer: queue.Queue[DomainEvent] = queue.Queue(maxsize=max_buffer)
        self._stop = threading.Event()
        self.dropped_count = 0
        self.sent_count = 0
        self.failed_count = 0
        self._thread = threading.Thread(
            target=self._drain_loop, daemon=True, name="event-sender"
        )
        self._thread.start()

    def publish(self, event: DomainEvent) -> None:
        try:
            self._buffer.put_nowait(event)
            return
        except queue.Full:
            pass

        is_critical = isinstance(event, SafetyEvent) and event.severity == Severity.CRITICAL
        if is_critical:
            try:
                dropped = self._buffer.get_nowait()
                self._buffer.task_done()
                self.dropped_count += 1
                log.warning("Dropped older event %s for CRITICAL event", dropped.event_id)
                self._buffer.put_nowait(event)
                return
            except (queue.Empty, queue.Full):
                pass
        self.dropped_count += 1
        log.warning("Event buffer full; dropped event %s", event.event_id)

    def _drain_loop(self) -> None:
        while not self._stop.is_set() or not self._buffer.empty():
            try:
                event = self._buffer.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.transport.send(event)
                self.sent_count += 1
            except Exception:
                self.failed_count += 1
                log.exception("Event transport failed for %s", event.event_id)
            finally:
                self._buffer.task_done()

    def stats(self) -> dict[str, int]:
        return {
            "sent": self.sent_count,
            "failed": self.failed_count,
            "dropped": self.dropped_count,
            "pending": self._buffer.qsize(),
        }

    def close(self, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while self._buffer.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        self._stop.set()
        self._thread.join(timeout=1.0)
