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

