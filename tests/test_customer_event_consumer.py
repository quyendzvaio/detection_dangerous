import json

from customer_host.event_consumer import CustomerEventConsumer, LocalEventStore


def test_customer_consumer_is_idempotent(tmp_path):
    store = LocalEventStore(str(tmp_path / "events.sqlite3"))
    consumer = CustomerEventConsumer(store)
    payload = json.dumps(
        {
            "tenant_key": "tenant-a",
            "device_key": "edge-a",
            "camera_key": "cam-1",
            "idempotency_key": "event-1",
            "payload": {"event_id": "event-1", "camera_id": 1},
        }
    )
    assert consumer.handle_message(payload.encode())
    assert not consumer.handle_message(payload.encode())
    store.close()

