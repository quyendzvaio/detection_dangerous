import json

import pytest

from edge_agent.messaging import FireAndForgetPublisher, MessageEnvelope, MqttTopic
from edge_agent.stream_publish import PublishSpec, build_ffmpeg_publish_command


class FakeTransport:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def publish(self, topic, payload, *, qos=0, retain=False):
        if self.fail:
            raise RuntimeError("offline")
        self.calls.append((topic, payload, qos, retain))


def test_mqtt_envelope_preserves_payload_and_uses_fire_and_forget():
    transport = FakeTransport()
    publisher = FireAndForgetPublisher(transport)
    envelope = MessageEnvelope("t1", "d1", "c1", "event-1", {"event_id": "event-1", "camera_id": 1})
    assert publisher.publish(MqttTopic("events", "t1", "d1", "c1"), envelope)
    topic, payload, qos, retain = transport.calls[0]
    assert topic == "events/t1/d1/c1"
    assert qos == 0 and retain is False
    assert json.loads(payload)["payload"]["camera_id"] == 1


def test_mqtt_publish_does_not_retry_or_raise_when_offline():
    assert not FireAndForgetPublisher(FakeTransport(fail=True)).publish(
        MqttTopic("status", "t1", "d1"),
        MessageEnvelope("t1", "d1", "", "status-1", {}),
    )


def test_ffmpeg_device_publish_keeps_quality_defaults():
    command = build_ffmpeg_publish_command(
        PublishSpec("/dev/video0", "rtsps://ingress/tenants/t1/cameras/c1/main", source_is_device=True)
    )
    assert "1280x720" in command
    assert "25" in command
    assert command[-1].startswith("rtsps://")


def test_mqtt_topic_rejects_unscoped_segments():
    with pytest.raises(ValueError):
        MqttTopic("events", "tenant/other", "device", "camera")


def test_paho_transport_requires_complete_credentials(monkeypatch):
    import sys
    import types

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def username_pw_set(self, *_args):
            raise AssertionError("partial credentials must fail before authentication")

    fake_mqtt = types.SimpleNamespace(
        CallbackAPIVersion=types.SimpleNamespace(VERSION2=2),
        MQTTv5=5,
        Client=FakeClient,
    )
    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.ModuleType("paho.mqtt"))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", fake_mqtt)

    from edge_agent.messaging import PahoMqttTransport

    try:
        PahoMqttTransport("mqtt", username="only-user")
    except ValueError as exc:
        assert "provided together" in str(exc)
    else:
        raise AssertionError("partial MQTT credentials were accepted")


def test_paho_transport_uses_required_ca_verification(monkeypatch, tmp_path):
    import ssl
    import sys
    import types

    captured = {}

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def username_pw_set(self, username, password):
            captured["credentials"] = (username, password)

        def tls_set(self, **kwargs):
            captured["tls"] = kwargs

        def connect(self, host, port):
            captured["endpoint"] = (host, port)

        def loop_start(self):
            pass

        def loop_stop(self):
            pass

        def disconnect(self):
            pass

    fake_mqtt = types.SimpleNamespace(
        CallbackAPIVersion=types.SimpleNamespace(VERSION2=2),
        MQTTv5=5,
        Client=FakeClient,
    )
    monkeypatch.setitem(sys.modules, "paho", types.ModuleType("paho"))
    monkeypatch.setitem(sys.modules, "paho.mqtt", types.ModuleType("paho.mqtt"))
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", fake_mqtt)

    ca_file = tmp_path / "ca.crt"
    ca_file.write_text("test-ca")
    from edge_agent.messaging import PahoMqttTransport

    transport = PahoMqttTransport(
        "mqtt",
        username="user",
        password="password",
        tls_ca_file=str(ca_file),
    )
    transport.close()
    assert captured["credentials"] == ("user", "password")
    assert captured["endpoint"] == ("mqtt", 8883)
    assert captured["tls"] == {
        "ca_certs": str(ca_file),
        "cert_reqs": ssl.CERT_REQUIRED,
    }
