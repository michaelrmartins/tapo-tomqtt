# tapo-tomqtt

Reads **TP-Link Tapo** smart plugs (focused on the **P110**) directly over the
local network via [python-kasa](https://github.com/python-kasa/python-kasa) and
publishes their data to an **MQTT** broker. Nothing goes to the internet —
communication is direct with the plug.

Besides the documented values (energy, signal, LED, etc.) it also retrieves
**voltage and current** through the undocumented `get_emeter_data` call, which
the P110/P115 firmware answers even though no official API exposes it:

```json
{"current_ma": 744, "voltage_mv": 234120, "power_mw": 141916}
```

It runs **one-shot**: reads every device once, publishes one JSON message per
device, then exits. Ideal for scheduling with cron.

## Published payload

Topic: `<topic_prefix>/<name-slug>` — e.g. `tapo/nobreak-internet-p110`

```json
{
  "timestamp": "2026-09-21T22:40:42-03:00",
  "name": "Nobreak - Internet - P110",
  "host": "10.192.100.92",
  "state": true,
  "power_w": 50.776,
  "voltage_v": 127.7,
  "current_a": 0.59,
  "signal_level": 2,
  "rssi": -57,
  "ssid": "2 - Sunshine Network",
  "cloud_connection": true,
  "consumption_today_kwh": 1.102,
  "consumption_this_month_kwh": 24.842,
  "update_available": null,
  "led": true,
  "device_id": "8022DFA639E4FCED94D60921DC26082B23B49055",
  "on_since": "2026-09-20T16:49:35-03:00"
}
```

If the plug does not answer `get_emeter_data`, `voltage_v`/`current_a` come back
as `null` and `power_w` falls back to the documented instantaneous consumption.

---

## Installing on a new server

Requirements: **Python 3.11+**, network access to both the plugs and the MQTT
broker.

### 1. Copy the project

```bash
git clone <repo-url> tapo-tomqtt   # or copy the folder over
cd tapo-tomqtt
```

### 2. System dependencies (Debian/Ubuntu)

The system Python is usually *externally-managed* (PEP 668), so you need the
virtualenv package:

```bash
sudo apt update
sudo apt install -y python3-venv        # older releases: python3.11-venv
```

### 3. Virtual environment + Python libs

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

### 4. TP-Link account credentials (`.env` file)

Credentials live in a `.env` file (kept out of git, with restricted
permissions):

```bash
cp .env.example .env
nano .env            # fill in TAPO_EMAIL and TAPO_PASSWORD
chmod 600 .env
```

The `.env` file is loaded automatically. Variables already exported in the
environment take precedence over the file.

> In the Tapo app, enable **Me → Third-Party Services → Third-Party
> Compatibility** (power-cycle the plug if the first connection is refused).

### 5. Configure devices and broker

```bash
cp config.example.json config.json
nano config.json
```

```json
{
  "mqtt": {
    "host": "10.192.100.11",
    "port": 1883,
    "topic_prefix": "tapo",
    "qos": 0,
    "retain": true,
    "client_id": "tapo-tomqtt"
  },
  "devices": [
    { "name": "Nobreak - Internet - P110", "host": "10.192.100.92" }
  ]
}
```

Add as many devices to `devices` as you like — they are read in parallel.

### 6. Test

```bash
./venv/bin/python main.py --dry-run   # read and print, without publishing
./venv/bin/python main.py             # read and publish to the broker
```

Check on the broker (if you have `mosquitto-clients`):

```bash
mosquitto_sub -h 10.192.100.11 -t 'tapo/#' -v
```

---

## Scheduling (cron)

Since credentials live in `.env`, the crontab stays clean (no password):

```cron
# every minute
* * * * * cd /home/mike/documents/projects/tapo-tomqtt && ./venv/bin/python main.py >> /tmp/tapo.log 2>&1
```

## Usage

```bash
./venv/bin/python main.py             # read and publish
./venv/bin/python main.py --dry-run   # read and print, without publishing
./venv/bin/python main.py -c /path/to/config.json
```

Exit code: `0` if at least one device was published, `1` otherwise.

## Files

| File                  | Purpose                                           |
|-----------------------|---------------------------------------------------|
| `main.py`             | orchestrates: reads all, publishes, sets exit code|
| `reader.py`           | reads one plug (features + `get_emeter_data`)      |
| `publisher.py`        | publishes the JSON payloads to the MQTT broker     |
| `config.py`           | loads `config.json`, `.env` and credentials        |
| `config.example.json` | configuration template                            |
| `.env.example`        | TP-Link credentials template                       |
