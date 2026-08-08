"""Placeholder runtime for the customer-host MQTT consumer container.

The Paho callback wiring is intentionally isolated from the idempotent
CustomerEventConsumer so it can be replaced with the customer's local
backend adapter without changing storage semantics.
"""

from __future__ import annotations

import os
import ssl

from customer_host.event_consumer import CustomerEventConsumer, LocalEventStore


def main() -> int:
    store = LocalEventStore(os.environ.get("LOCAL_EVENT_DB", "customer-events.sqlite3"))
    consumer = CustomerEventConsumer(store)
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise SystemExit("paho-mqtt is required for the customer MQTT consumer") from exc

    tenant_key = os.environ["TENANT_KEY"]
    device_key = os.environ["DEVICE_KEY"]
    topic = f"events/{tenant_key}/{device_key}/#"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
    username = os.environ.get("MQTT_USERNAME")
    if username:
        client.username_pw_set(username, os.environ.get("MQTT_PASSWORD"))
    ca_file = os.environ.get("MQTT_CA_FILE")
    if ca_file:
        client.tls_set(ca_certs=ca_file, cert_reqs=ssl.CERT_REQUIRED)

    def on_message(_client, _userdata, message):
        try:
            consumer.handle_message(message.payload)
        except Exception as exc:
            # Fire-and-forget delivery must not take down the local consumer.
            print(f"[event-consumer] invalid message: {exc}", flush=True)

    client.on_message = on_message
    client.connect(os.environ["MQTT_HOST"], int(os.environ.get("MQTT_PORT", "8883")))
    client.subscribe(topic, qos=0)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        client.disconnect()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
