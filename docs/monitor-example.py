"""Log mains voltage and power from TP-Link Tapo smart plugs to a CSV file.

Voltage comes from the undocumented `get_emeter_data` call (fields
voltage_mv / current_ma / power_mw), which the plug's firmware answers even
though no official API or app exposes it. Verified on Tapo P110 (EU,
hw 1.0, fw 1.4.6); P115 shares the same metering firmware. If a plug does
not answer that call, the script falls back to power-only logging via the
documented `get_energy_usage` and says so clearly.

Setup:
  1. Tapo app -> Me -> Third-Party Services -> enable Third-Party Compatibility
     (power-cycle the plugs afterwards if the first connection is refused).
  2. Set TAPO_EMAIL / TAPO_PASSWORD environment variables (TP-Link account).
  3. Put your plugs' names and IPs in config.json.
"""

import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime

from kasa import Discover

from common import load_config

CFG = load_config()

# on_time counter drift/latency tolerance before we call it a power loss
OUTAGE_MARGIN_S = 60


async def connect(ip, email, password):
    return await Discover.discover_single(ip, username=email, password=password)


async def probe_mode(device):
    """Return "voltage" if get_emeter_data works, else "power-only"."""
    try:
        res = await device.protocol.query({"get_emeter_data": None})
        if "voltage_mv" in res["get_emeter_data"]:
            return "voltage"
    except Exception:
        pass
    return "power-only"


async def read_sample(device, mode):
    """Return (voltage_V or None, power_W, on_time_s or None)."""
    if mode == "voltage":
        res = await device.protocol.query(
            {"get_emeter_data": None, "get_device_info": None})
        d = res["get_emeter_data"]
        on_time = res["get_device_info"].get("on_time")
        return d["voltage_mv"] / 1000.0, d.get("power_mw", 0) / 1000.0, on_time
    res = await device.protocol.query(
        {"get_energy_usage": None, "get_device_info": None})
    return (None,
            res["get_energy_usage"].get("current_power", 0) / 1000.0,
            res["get_device_info"].get("on_time"))


def load_state():
    try:
        with open(CFG["state_path"], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(CFG["state_path"], "w", encoding="utf-8") as f:
        json.dump(state, f)


def check_outage(plug, on_time, now_ts, state):
    """Detect a power loss via the plug's on_time counter.

    on_time counts seconds since the plug got power. If it is smaller than
    it should be given the last observation, the plug rebooted — i.e. power
    was lost somewhere in between (works across logger restarts too, since
    state is persisted). Returns (last_seen_ts, restored_ts) or None.
    """
    prev = state.get(plug)
    state[plug] = {"t": now_ts, "on_time": on_time}
    if prev is None or on_time is None or prev.get("on_time") is None:
        return None
    expected = prev["on_time"] + (now_ts - prev["t"])
    if on_time + OUTAGE_MARGIN_S < expected:
        restored = now_ts - on_time
        return prev["t"], max(restored, prev["t"] + 1)
    return None


def record_outage(plug, last_seen_ts, restored_ts):
    path = CFG["outages_path"]
    new = not path.exists() or path.stat().st_size == 0
    iso = lambda ts: datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["last_seen", "power_restored", "plug_name"])
        w.writerow([iso(last_seen_ts), iso(restored_ts), plug])


async def close_quietly(device):
    try:
        await device.protocol.close()
    except Exception:
        pass


async def main():
    email = os.environ.get("TAPO_EMAIL")
    password = os.environ.get("TAPO_PASSWORD")
    if not email or not password:
        print("ERROR: set TAPO_EMAIL and TAPO_PASSWORD environment variables "
              "(your TP-Link account credentials).")
        sys.exit(1)

    plugs = CFG["plugs"]
    interval = CFG["interval_seconds"]
    log_path = CFG["log_path"]

    devices, modes = {}, {}
    print(f"Probing {len(plugs)} plug(s)...")
    for name, ip in plugs.items():
        try:
            devices[name] = await connect(ip, email, password)
            modes[name] = await probe_mode(devices[name])
            print(f"  {name} ({ip}): {modes[name]}")
        except Exception as e:
            print(f"  {name} ({ip}): connection failed ({type(e).__name__}: {e}) "
                  f"- will keep retrying")

    if modes and all(m == "power-only" for m in modes.values()):
        print("\nNOTE: none of your plugs answered get_emeter_data - this "
              "firmware does not expose voltage. Logging power only; the "
              "voltage column will stay empty.")

    write_header = not log_path.exists() or log_path.stat().st_size == 0
    state = load_state()
    print(f"\nLogging every {interval}s -> {log_path} (Ctrl+C to stop)")

    loop = asyncio.get_running_loop()
    while True:
        cycle_start = loop.time()
        rows = []
        for name, ip in plugs.items():
            try:
                if name not in devices:
                    devices[name] = await connect(ip, email, password)
                    modes[name] = await probe_mode(devices[name])
                voltage, power, on_time = await read_sample(devices[name], modes[name])
                now_ts = time.time()
                outage = check_outage(name, on_time, now_ts, state)
                if outage:
                    record_outage(name, *outage)
                    print(f"*** POWER OUTAGE detected on '{name}': plug lost "
                          f"power after {datetime.fromtimestamp(outage[0]):%Y-%m-%d %H:%M:%S}, "
                          f"restored around {datetime.fromtimestamp(outage[1]):%Y-%m-%d %H:%M:%S}")
                ts = datetime.now().astimezone().isoformat(timespec="seconds")
                v_str = f"{voltage:.1f}" if voltage is not None else ""
                rows.append([ts, name, v_str, f"{power:.1f}"])
                v_disp = f"{voltage:6.1f} V" if voltage is not None else "   -   "
                print(f"[{ts}] {name:12s} {v_disp}  {power:7.1f} W")
            except Exception as e:
                dead = devices.pop(name, None)
                if dead is not None:
                    await close_quietly(dead)
                print(f"[{datetime.now().isoformat(timespec='seconds')}] "
                      f"{name}: ERROR {type(e).__name__}: {e}")

        if rows:
            with open(log_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow(["timestamp", "plug_name", "voltage_V", "power_W"])
                    write_header = False
                writer.writerows(rows)
            save_state(state)

        # fixed cadence: subtract the time spent querying the plugs
        await asyncio.sleep(max(0.5, interval - (loop.time() - cycle_start)))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")