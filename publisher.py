"""Publish device payloads to the MQTT broker in one shot.

Uses paho's fire-and-forget publish.multiple(): it opens a single connection,
sends every message and disconnects - a good fit for a one-shot cron run.
The broker is assumed anonymous (no username/password/TLS).
"""

import json

import paho.mqtt.publish as publish


def publish_all(mqtt_cfg, messages):
    """messages: list of (topic, payload_dict). Payloads are JSON-encoded."""
    msgs = [
        {
            "topic": topic,
            "payload": json.dumps(payload, ensure_ascii=False),
            "qos": mqtt_cfg["qos"],
            "retain": mqtt_cfg["retain"],
        }
        for topic, payload in messages
    ]
    publish.multiple(
        msgs,
        hostname=mqtt_cfg["host"],
        port=mqtt_cfg["port"],
        client_id=mqtt_cfg["client_id"],
    )
