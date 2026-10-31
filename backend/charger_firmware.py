"""Firmware des Ladekoffers: Datei hochladen und dem Koffer per WLAN zum Update anbieten."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Final, Optional

DIR: Final[str] = os.environ.get(
    "FIRMWARE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware_cache")
)
FILE: Final[str] = os.path.join(DIR, "ladekoffer.bin")
META_KEY: Final[str] = "CHARGER_FW"
# Die Firmware enthaelt diese Kennung (siehe config.h), daraus liest der Pi die Version
MARKER_RE: Final[re.Pattern[bytes]] = re.compile(rb"KOFFER-FW:(v\d+\.\d+\.\d+)")
MAX_SIZE: Final[int] = 1_310_720  # eine OTA-Partition
MIN_SIZE: Final[int] = 100_000


def validate(data: bytes) -> str:
    """Prueft die Datei und liefert die Version. Wirft ValueError mit Klartext."""
    if len(data) < MIN_SIZE or data[0] != 0xE9:
        raise ValueError("Das ist keine ESP32-Firmware (firmware.bin).")
    if len(data) > MAX_SIZE:
        raise ValueError("Die Firmware ist groesser als eine Update-Partition.")
    m = MARKER_RE.search(data)
    if not m:
        raise ValueError("Keine Koffer-Firmware (ab v0.4.0) erkannt.")
    return m.group(1).decode()


def save(redis_store: Any, data: bytes) -> dict[str, Any]:
    version = validate(data)
    os.makedirs(DIR, exist_ok=True)
    tmp = FILE + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, FILE)
    meta = {"version": version, "md5": hashlib.md5(data).hexdigest(), "size": len(data), "ts": int(time.time() * 1000)}
    redis_store.set(META_KEY, json.dumps(meta))
    return meta


def meta(redis_store: Any) -> Optional[dict[str, Any]]:
    raw = redis_store.get(META_KEY)
    if not raw or not os.path.isfile(FILE):
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def clear(redis_store: Any) -> None:
    redis_store.delete(META_KEY)
    try:
        os.remove(FILE)
    except OSError:
        pass


def offer(redis_store: Any, running: str) -> Optional[dict[str, Any]]:
    """Angebot fuer den Koffer, solange er nicht die hochgeladene Version laeuft."""
    m = meta(redis_store)
    if not m or m.get("version") == running:
        return None
    return {"version": m["version"], "md5": m["md5"], "size": m["size"]}
