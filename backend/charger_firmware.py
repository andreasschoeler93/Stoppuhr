"""Firmware des Ladekoffers: Datei hochladen und dem Koffer per WLAN zum Update anbieten."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Final, Optional

import firmware_store

DIR: Final[str] = os.environ.get(
    "FIRMWARE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware_cache")
)
FILE: Final[str] = os.path.join(DIR, "ladekoffer.bin")
META_KEY: Final[str] = "CHARGER_FW"
# Die Firmware enthaelt diese Kennung (siehe config.h), daraus liest der Pi die Version
MARKER_RE: Final[re.Pattern[bytes]] = re.compile(rb"KOFFER-FW:(v\d+\.\d+\.\d+)")
MAX_SIZE: Final[int] = 1_310_720  # eine OTA-Partition
MIN_SIZE: Final[int] = 100_000


REPO: Final[str] = os.environ.get("CHARGER_FIRMWARE_REPO", "andreasschoeler93/Stoppuhr-2.0-Ladekoffer")
ASSET_NAME: Final[str] = "firmware.bin"
# Erste Version, die ihre Zugangsdaten im Flash speichert und deshalb als fertige Release-Datei laeuft
MIN_VERSION: Final[tuple[int, int, int]] = (0, 5, 0)
_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def list_releases(ttl_s: int = 120) -> list[dict[str, Any]]:
    """Releases mit firmware.bin ab MIN_VERSION, neueste zuerst (GitHub, kurz zwischengespeichert)."""
    if _cache["data"] is not None and time.time() - _cache["ts"] < ttl_s:
        return _cache["data"]
    with firmware_store._get(f"https://api.github.com/repos/{REPO}/releases?per_page=100") as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for rel in data:
        tag = str(rel.get("tag_name", ""))
        ver = firmware_store.parse_tag(tag)
        if ver is None or ver < MIN_VERSION or rel.get("draft") or rel.get("prerelease"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET_NAME), None)
        if asset is None:
            continue
        out.append({"tag": tag, "published": rel.get("published_at"), "size": asset.get("size"), "url": asset.get("browser_download_url")})
    out.sort(key=lambda r: firmware_store.parse_tag(r["tag"]) or (0, 0, 0), reverse=True)
    _cache["ts"], _cache["data"] = time.time(), out
    return out


def download_release(redis_store: Any, tag: str) -> dict[str, Any]:
    """Laedt das Release von GitHub und stellt es dem Koffer bereit."""
    release = next((r for r in list_releases() if r["tag"] == tag), None)
    if release is None:
        raise ValueError("Version nicht gefunden")
    if not str(release["url"]).startswith(firmware_store.ALLOWED_HOSTS):
        raise ValueError("Download-Adresse nicht erlaubt")
    with firmware_store._get(release["url"]) as resp:
        data = resp.read(MAX_SIZE + 1)
    meta_ = save(redis_store, data)
    if meta_["version"] != tag:
        clear(redis_store)
        raise ValueError("Die Datei enthaelt eine andere Version als das Release")
    return meta_


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
