"""Load and validate the JSON configuration file.

Layout (see config.example.json):

    {
      "mqtt":   { "host", "port", "topic_prefix", "qos", "retain", "client_id" },
      "devices": [ { "name", "host" }, ... ]
    }

TP-Link account credentials are NOT stored here - they come from the
TAPO_EMAIL / TAPO_PASSWORD environment variables so secrets stay out of the
config file. As a fallback, an optional top-level "tapo": {"email", "password"}
block is also accepted.
"""

import json
import os
import re
import sys
from pathlib import Path

DEFAULT_CONFIG_PATH = Path(__file__).with_name("config.json")
DEFAULT_ENV_PATH = Path(__file__).with_name(".env")


def load_dotenv(path=None):
    """Load KEY=VALUE pairs from a .env file into os.environ.

    Minimal parser (no dependency): ignores blank lines and '#' comments,
    strips surrounding quotes, and does NOT override variables already set in
    the real environment - so an explicit export still wins over the file.
    """
    path = Path(path) if path else DEFAULT_ENV_PATH
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def slugify(name):
    """Turn a device name into an MQTT-safe topic segment.

    "Nobreak - Internet - P110" -> "nobreak-internet-p110"
    """
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "device"


def load_config(path=None):
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not path.exists():
        sys.exit(f"ERROR: config file not found: {path}\n"
                 f"Copy config.example.json to {path.name} and edit it.")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path} is not valid JSON: {e}")

    mqtt = cfg.setdefault("mqtt", {})
    if not mqtt.get("host"):
        sys.exit("ERROR: config 'mqtt.host' is required.")
    mqtt.setdefault("port", 1883)
    mqtt.setdefault("topic_prefix", "tapo")
    mqtt.setdefault("qos", 0)
    mqtt.setdefault("retain", True)
    mqtt.setdefault("client_id", "tapo-tomqtt")

    devices = cfg.get("devices") or []
    if not devices:
        sys.exit("ERROR: config 'devices' must list at least one device.")
    for d in devices:
        if not d.get("host"):
            sys.exit(f"ERROR: every device needs a 'host': {d}")
        d.setdefault("name", d["host"])
        d["topic"] = f"{mqtt['topic_prefix']}/{slugify(d['name'])}"

    return cfg


def get_credentials(cfg):
    """Return (email, password).

    Resolution order: real environment variables > .env file > optional
    "tapo" block in config.json. Loading .env never overrides an already-set
    variable, so the order above holds.
    """
    load_dotenv()
    tapo = cfg.get("tapo", {})
    email = os.environ.get("TAPO_EMAIL") or tapo.get("email")
    password = os.environ.get("TAPO_PASSWORD") or tapo.get("password")
    if not email or not password:
        sys.exit("ERROR: set TAPO_EMAIL and TAPO_PASSWORD environment variables "
                 "(your TP-Link account credentials).")
    return email, password
