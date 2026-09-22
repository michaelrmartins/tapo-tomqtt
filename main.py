#!/usr/bin/env python3
"""tapo-tomqtt: read Tapo plugs on the local network and publish to MQTT.

One-shot: reads every configured device once, publishes one JSON message per
device to `<topic_prefix>/<slug>`, then exits. Schedule it with cron, e.g.:

    * * * * * cd /path/to/tapo-tomqtt && TAPO_EMAIL=... TAPO_PASSWORD=... \
        ./venv/bin/python main.py >> tapo.log 2>&1

Exit code is 0 if at least one device was published, 1 otherwise.
"""

import argparse
import asyncio
import sys

from config import get_credentials, load_config
from publisher import publish_all
from reader import read_device


async def gather_devices(devices, email, password):
    tasks = [read_device(d["name"], d["host"], email, password) for d in devices]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return list(zip(devices, results))


def main():
    parser = argparse.ArgumentParser(description="Read Tapo plugs and publish to MQTT.")
    parser.add_argument("-c", "--config", help="path to config.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="read and print payloads without publishing")
    args = parser.parse_args()

    cfg = load_config(args.config)
    email, password = get_credentials(cfg)

    outcomes = asyncio.run(gather_devices(cfg["devices"], email, password))

    messages, failures = [], 0
    for device, result in outcomes:
        label = f"{device['name']} ({device['host']})"
        if isinstance(result, Exception):
            failures += 1
            print(f"[FAIL] {label}: {type(result).__name__}: {result}", file=sys.stderr)
            continue
        messages.append((device["topic"], result))
        power = result.get("power_w")
        volt = result.get("voltage_v")
        v = f"{volt} V" if volt is not None else "no voltage"
        print(f"[ OK ] {label} -> {device['topic']}  {power} W, {v}")

    if not messages:
        print("Nothing to publish - all devices failed.", file=sys.stderr)
        return 1

    if args.dry_run:
        import json
        for topic, payload in messages:
            print(f"\n{topic}\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        return 0 if failures == 0 else 1

    try:
        publish_all(cfg["mqtt"], messages)
    except Exception as e:
        print(f"ERROR publishing to MQTT {cfg['mqtt']['host']}:{cfg['mqtt']['port']}: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1

    print(f"Published {len(messages)} device(s) to "
          f"{cfg['mqtt']['host']}:{cfg['mqtt']['port']}"
          + (f" ({failures} failed)" if failures else ""))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
