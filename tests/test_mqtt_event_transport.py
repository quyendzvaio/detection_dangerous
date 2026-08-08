from ai_engine.contracts.event_schema import CameraStatus, CameraStatusEvent
from ai_engine.events import MqttEventTransport


def test_mqtt_event_transport_preserves_backend_payload(monkeypatch):
    captured = {}

    class FakePublisher:
        def __init__(self, transport):
            pass

        def publish(self, topic, envelope):
            captured["topic"] = str(topic)
            captured["payload"] = envelope.payload
            return True

    monkeypatch.setattr("ai_engine.events.FireAndForgetPublisher", FakePublisher)
    monkeypatch.setattr("ai_engine.events.PahoMqttTransport", lambda host, port: object())
    transport = MqttEventTransport("mqtt", "tenant-a", "device-a", "camera-a")
    event = CameraStatusEvent(camera_id=1, status=CameraStatus.ONLINE, observed_at=1.0)
    transport.send(event)
    assert captured["topic"] == "events/tenant-a/device-a/camera-a"
    assert captured["payload"]["event_category"] == "CAMERA_STATUS"
    assert captured["payload"]["camera_id"] == 1

