"""Read one Tapo plug over the local network and return a flat dict of values.

Two sources are combined:

* python-kasa's high-level *feature* API (device.features[<id>].value) for the
  documented values - the same ids you see in `kasa --host <ip> feature`:
  state, signal_level, cloud_connection, consumption_today,
  consumption_this_month, update_available, led, device_id, rssi, ssid,
  on_since, current_consumption.

* the undocumented `get_emeter_data` protocol call for mains voltage/current,
  which the P110/P115 firmware answers even though no official API exposes it:
      {"current_ma": 744, "voltage_mv": 234120, "power_mw": 141916}
  If the plug does not answer it, voltage/current come back as None and power
  falls back to the documented current_consumption feature.
"""

from datetime import datetime

from kasa import Discover


def _feat(device, feature_id):
    """Feature value if the device exposes it, else None."""
    feature = device.features.get(feature_id)
    return feature.value if feature is not None else None


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


async def _read_emeter(device):
    """Return (voltage_V, current_A, power_W) or (None, None, None)."""
    try:
        res = await device.protocol.query({"get_emeter_data": None})
        d = res["get_emeter_data"]
        if "voltage_mv" in d:
            return (
                d["voltage_mv"] / 1000.0,
                d.get("current_ma", 0) / 1000.0,
                d.get("power_mw", 0) / 1000.0,
            )
    except Exception:
        pass
    return None, None, None


async def read_device(name, host, email, password):
    """Connect, update and read a single plug. Returns a payload dict."""
    device = await Discover.discover_single(host, username=email, password=password)
    try:
        await device.update()
        voltage, current, power = await _read_emeter(device)
        if power is None:
            power = _feat(device, "current_consumption")

        return {
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "name": name,
            "host": host,
            "state": _feat(device, "state"),
            "power_w": round(power, 3) if power is not None else None,
            "voltage_v": round(voltage, 1) if voltage is not None else None,
            "current_a": round(current, 3) if current is not None else None,
            "signal_level": _feat(device, "signal_level"),
            "rssi": _feat(device, "rssi"),
            "ssid": _feat(device, "ssid"),
            "cloud_connection": _feat(device, "cloud_connection"),
            "consumption_today_kwh": _feat(device, "consumption_today"),
            "consumption_this_month_kwh": _feat(device, "consumption_this_month"),
            "update_available": _feat(device, "update_available"),
            "led": _feat(device, "led"),
            "device_id": _feat(device, "device_id"),
            "on_since": _iso(_feat(device, "on_since")),
        }
    finally:
        try:
            await device.protocol.close()
        except Exception:
            pass
