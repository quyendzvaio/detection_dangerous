"""Non-blocking, bounded delivery of typed AI domain events."""
from __future__ import annotations

import logging
import queue
import random
import threading
import time
from abc import ABC, abstractmethod
from typing import Callable

from ai_engine.contracts.event_schema import (
    CameraStatusEvent,
    DomainEvent,
    SafetyEvent,
    Severity,
)
from edge_agent.messaging import FireAndForgetPublisher, MessageEnvelope, MqttTopic, PahoMqttTransport

log = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    """An event could not be delivered to its destination."""


class EventTransport(ABC):
    """Blocking transport interface; EventBus calls it only from its sender thread."""

    @abstractmethod
    def send(self, event: DomainEvent) -> None:
        raise NotImplementedError


class HttpEventTransport(EventTransport):
    """HTTP transport with service auth and retry for transient failures only."""

    RETRYABLE_STATUS_CODES = {408, 425, 429}

    def __init__(
        self,
        event_url: str = "http://localhost:8080/api/v1/internal/events",
        camera_status_url: str | None = None,
        service_token: str | None = None,
        timeout: float = 3.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        session=None,
    ) -> None:
        self.event_url = event_url
        self.camera_status_url = camera_status_url or event_url.rsplit("/", 1)[0] + "/camera-status"
        self.service_token = service_token
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self._session = session

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _url_for(self, event: DomainEvent) -> str:
        if isinstance(event, CameraStatusEvent):
            return self.camera_status_url
        return self.event_url

    def send(self, event: DomainEvent) -> None:
        session = self._get_session()
        headers = (
            {"Authorization": f"Bearer {self.service_token}"}
            if self.service_token
            else {}
        )
        url = self._url_for(event)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = session.post(
                    url,
                    json=event.to_backend_payload(),
                    headers=headers,
                    timeout=self.timeout,
                )
                if 200 <= response.status_code < 300:
                    return
                body = getattr(response, "text", "")[:500]
                error = DeliveryError(
                    f"backend returned HTTP {response.status_code} for event "
                    f"{event.event_id}: {body}"
                )
                if not (
                    response.status_code in self.RETRYABLE_STATUS_CODES
                    or response.status_code >= 500
                ):
                    raise error
                last_error = error
            except DeliveryError:
                raise
            except Exception as exc:
                last_error = exc

            log.warning(
                "Event %s delivery failed on attempt %d/%d: %s",
                event.event_id,
                attempt + 1,
                self.retries + 1,
                last_error,
            )
            if attempt < self.retries:
                delay = self.backoff_seconds * (2**attempt)
                time.sleep(delay + random.uniform(0.0, delay * 0.2))

        raise DeliveryError(
            f"event {event.event_id} failed after {self.retries + 1} attempts"
        ) from last_error


class MqttEventTransport(EventTransport):
    """Outbound-only QoS 0 transport for server-to-customer delivery."""

    def __init__(
        self,
        host: str,
        tenant_key: str,
        device_key: str,
        camera_key: str,
        port: int = 8883,
        username: str | None = None,
        password: str | None = None,
        tls_ca_file: str | None = None,
    ):
        self._publisher = FireAndForgetPublisher(
            PahoMqttTransport(
                host,
                port,
                username=username,
                password=password,
                tls_ca_file=tls_ca_file,
            )
        )
        self._tenant_key = tenant_key
        self._device_key = device_key
        self._camera_key = camera_key

    def send(self, event: DomainEvent) -> None:
        payload = event.to_backend_payload()
        envelope = MessageEnvelope(
            tenant_key=self._tenant_key,
            device_key=self._device_key,
            camera_key=self._camera_key,
            idempotency_key=str(payload["event_id"]),
            payload=payload,
        )
        ok = self._publisher.publish(
            MqttTopic("events", self._tenant_key, self._device_key, self._camera_key),
            envelope,
        )
        if not ok:
            raise DeliveryError(f"MQTT publish failed for event {payload['event_id']}")

    def close(self) -> None:
        transport = self._publisher.transport
        if hasattr(transport, "close"):
            transport.close()


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
        if max_buffer <= 0:
            raise ValueError("max_buffer must be positive")
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

    def publish(self, event: DomainEvent) -> bool:
        try:
            self._buffer.put_nowait(event)
            return True
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
                return True
            except (queue.Empty, queue.Full):
                pass
        self.dropped_count += 1
        log.warning("Event buffer full; dropped event %s", event.event_id)
        return False

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
        close_transport = getattr(self.transport, "close", None)
        if close_transport is not None:
            close_transport()
