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
    mqtt_args = {}

    def fake_transport(host, port, **kwargs):
        mqtt_args.update(host=host, port=port, **kwargs)
        return object()

    monkeypatch.setattr("ai_engine.events.PahoMqttTransport", fake_transport)
    transport = MqttEventTransport(
        "mqtt",
        "tenant-a",
        "device-a",
        "camera-a",
        username="mqtt-user",
        password="mqtt-password",
    )
    event = CameraStatusEvent(camera_id=1, status=CameraStatus.ONLINE, observed_at=1.0)
    transport.send(event)
    assert captured["topic"] == "events/tenant-a/device-a/camera-a"
    assert captured["payload"]["event_category"] == "CAMERA_STATUS"
    assert captured["payload"]["camera_id"] == 1
    assert mqtt_args == {
        "host": "mqtt",
        "port": 8883,
        "username": "mqtt-user",
        "password": "mqtt-password",
        "tls_ca_file": None,
    }
