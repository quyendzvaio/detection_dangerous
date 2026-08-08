import time

from ai_engine.contracts.event_schema import (
    CameraStatus,
    CameraStatusEvent,
    FallDetectedEvent,
)
from ai_engine.events import DeliveryError, EventBus, HttpEventTransport, InProcessTransport

NOW = 1_700_000_000.0


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def fall_event():
    return FallDetectedEvent(
        camera_id=1, track_id="cam1-7", detected_at=NOW, confidence=0.91
    )


def test_http_transport_routes_and_authenticates_camera_status():
    session = FakeSession([FakeResponse(201)])
    transport = HttpEventTransport(
        event_url="http://backend/internal/events",
        service_token="secret",
        session=session,
    )
    transport.send(
        CameraStatusEvent(
            camera_id=1,
            status=CameraStatus.ONLINE,
            observed_at=NOW,
        )
    )
    url, kwargs = session.calls[0]
    assert url == "http://backend/internal/camera-status"
    assert kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert kwargs["json"]["event_category"] == "CAMERA_STATUS"


def test_http_transport_retries_transient_but_not_validation_errors():
    retry_session = FakeSession([FakeResponse(503), FakeResponse(201)])
    HttpEventTransport(
        session=retry_session, retries=2, backoff_seconds=0
    ).send(fall_event())
    assert len(retry_session.calls) == 2

    permanent_session = FakeSession([FakeResponse(422, "invalid contract")])
    transport = HttpEventTransport(
        session=permanent_session, retries=2, backoff_seconds=0
    )
    try:
        transport.send(fall_event())
        raise AssertionError("HTTP 422 must fail without retry")
    except DeliveryError:
        pass
    assert len(permanent_session.calls) == 1


def test_event_bus_delivers_without_blocking_producer():
    delivered = []
    bus = EventBus(InProcessTransport(delivered), max_buffer=4)
    started = time.monotonic()
    assert bus.publish(fall_event()) is True
    assert time.monotonic() - started < 0.1
    bus.close(timeout=1.0)
    assert len(delivered) == 1
    assert bus.stats() == {"sent": 1, "failed": 0, "dropped": 0, "pending": 0}
