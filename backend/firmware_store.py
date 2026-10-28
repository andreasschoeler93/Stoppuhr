"""Firmware-Releases der Taster von GitHub holen und lokal zwischenspeichern."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from typing import Any, Final, Optional

REPO: Final[str] = os.environ.get("FIRMWARE_REPO", "andreasschoeler93/Taster")
CACHE_DIR: Final[str] = os.environ.get(
    "FIRMWARE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware_cache")
)
ASSET_NAME: Final[str] = "firmware.bin"
# Erste Version, die Zugangsdaten im Flash speichert und sich per Update installieren laesst
MIN_VERSION: Final[tuple[int, int, int]] = (0, 11, 0)
TAG_RE: Final[re.Pattern[str]] = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
ALLOWED_HOSTS: Final[tuple[str, ...]] = ("https://github.com/", "https://objects.githubusercontent.com/")
TIMEOUT_S: Final[int] = 10


def parse_tag(tag: str) -> Optional[tuple[int, int, int]]:
    m = TAG_RE.match(tag or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def _path(tag: str) -> str:
    if parse_tag(tag) is None:
        raise ValueError("ungueltiger Tag")
    return os.path.join(CACHE_DIR, f"{tag}.bin")


def cached_tags() -> list[str]:
    if not os.path.isdir(CACHE_DIR):
        return []
    tags = [f[:-4] for f in os.listdir(CACHE_DIR) if f.endswith(".bin") and parse_tag(f[:-4])]
    return sorted(tags, key=lambda t: parse_tag(t) or (0, 0, 0), reverse=True)


def cached_file(tag: str) -> Optional[str]:
    p = _path(tag)
    return p if os.path.isfile(p) else None


def file_info(tag: str) -> Optional[dict[str, Any]]:
    """Groesse und MD5 der zwischengespeicherten Datei."""
    p = cached_file(tag)
    if p is None:
        return None
    md5 = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            md5.update(chunk)
    return {"size": os.path.getsize(p), "md5": md5.hexdigest()}


def _get(url: str) -> urllib.request.addinfourl:
    req = urllib.request.Request(
        url, headers={"User-Agent": "stoppuhr-pi", "Accept": "application/vnd.github+json"}
    )
    return urllib.request.urlopen(req, timeout=TIMEOUT_S)  # noqa: S310 (feste https-URLs)


def list_releases() -> list[dict[str, Any]]:
    """Releases mit firmware.bin ab MIN_VERSION, neueste zuerst. Wirft bei Netzwerkfehlern."""
    with _get(f"https://api.github.com/repos/{REPO}/releases?per_page=100") as resp:
        data = json.loads(resp.read().decode("utf-8"))
    out = []
    for rel in data:
        tag = str(rel.get("tag_name", ""))
        ver = parse_tag(tag)
        if ver is None or ver < MIN_VERSION or rel.get("draft") or rel.get("prerelease"):
            continue
        asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET_NAME), None)
        if asset is None:
            continue
        out.append(
            {
                "tag": tag,
                "published": rel.get("published_at"),
                "size": asset.get("size"),
                "url": asset.get("browser_download_url"),
            }
        )
    out.sort(key=lambda r: parse_tag(r["tag"]) or (0, 0, 0), reverse=True)
    return out


_cache: dict[str, Any] = {"ts": 0.0, "data": None}


def list_releases_cached(ttl_s: int = 120) -> list[dict[str, Any]]:
    """Wie list_releases, aber hoechstens alle ttl_s Sekunden (GitHub-Limit ohne Anmeldung: 60/h)."""
    import time

    if _cache["data"] is not None and time.time() - _cache["ts"] < ttl_s:
        return _cache["data"]
    data = list_releases()
    _cache["ts"], _cache["data"] = time.time(), data
    return data


def download(tag: str, url: str) -> dict[str, Any]:
    """Laedt die Datei in den Zwischenspeicher (atomar). Gibt Groesse und MD5 zurueck."""
    if not url.startswith(ALLOWED_HOSTS):
        raise ValueError("Download-Adresse nicht erlaubt")
    dest = _path(tag)
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = dest + ".part"
    with _get(url) as resp, open(tmp, "wb") as f:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            f.write(chunk)
    # ESP32-Images beginnen immer mit dem Magic-Byte 0xE9
    with open(tmp, "rb") as f:
        if f.read(1) != b"\xe9":
            os.remove(tmp)
            raise ValueError("Datei ist keine ESP32-Firmware")
    os.replace(tmp, dest)
    info = file_info(tag)
    assert info is not None
    return info
