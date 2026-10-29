"""WLAN-Zugangsdaten (Koffer- und Bad-Netz), die Taster und Pis gemeinsam verwenden.

Ablauf einer Aenderung: Die Oberflaeche speichert eine neue Fassung (`version`). Die Taster holen sie
ueber /api/display, speichern sie vor und melden `wv` = version zurueck. Erst wenn alle online Taster
bestaetigt haben (oder der Nutzer es erzwingt), stellt jeder Pi seinen Zugangspunkt um (knoten_dienst.py).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from typing import Any, Final, Optional

WIFI_KEY: Final[str] = "WIFI_CFG"
TASTER_ONLINE_MS: Final[int] = 30_000
APPLIED_FILE: Final[str] = os.environ.get("WIFI_APPLIED_FILE", "/var/lib/stoppuhr-wlan-version")
AP_CONNECTION: Final[str] = os.environ.get("AP_CONNECTION", "ap")
# Die Firmware liest die Werte aus einfachem JSON ohne Escapes
_SAFE = re.compile(r'^[\x20-\x7e]+$')


def validate_ssid(ssid: str) -> Optional[str]:
    if not 1 <= len(ssid) <= 32 or not _SAFE.match(ssid) or '"' in ssid or "\\" in ssid:
        return "SSID: 1 bis 32 druckbare ASCII-Zeichen, ohne \" und \\"
    return None


def validate_psk(psk: str) -> Optional[str]:
    if not 8 <= len(psk) <= 63 or not _SAFE.match(psk) or '"' in psk or "\\" in psk:
        return "Kennwort: 8 bis 63 druckbare ASCII-Zeichen, ohne \" und \\"
    return None


def load(r: Any) -> Optional[dict[str, Any]]:
    raw = r.get(WIFI_KEY)
    return json.loads(raw) if raw else None


def save(r: Any, wifi1: dict[str, str], wifi2: dict[str, str]) -> dict[str, Any]:
    cfg = {"version": int(time.time()), "wifi1": wifi1, "wifi2": wifi2, "force": False}
    r.set(WIFI_KEY, json.dumps(cfg))
    return cfg


def set_force(r: Any) -> None:
    cfg = load(r)
    if cfg:
        cfg["force"] = True
        r.set(WIFI_KEY, json.dumps(cfg))


def offer_for(cfg: Optional[dict[str, Any]], vital: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Felder fuer /api/display: nur solange der Taster die aktuelle Fassung nicht bestaetigt hat."""
    if not cfg or (vital or {}).get("wv") == cfg["version"]:
        return {}
    return {
        "wifi_ver": cfg["version"],
        "wifi_ssid1": cfg["wifi1"]["ssid"],
        "wifi_pass1": cfg["wifi1"]["psk"],
        "wifi_ssid2": cfg["wifi2"]["ssid"],
        "wifi_pass2": cfg["wifi2"]["psk"],
    }


def taster_status(cfg: dict[str, Any], state: dict[str, Any], now_ms: int) -> dict[str, Any]:
    """Wer hat die aktuelle Fassung bestaetigt, wer fehlt (nur online Taster zaehlen)."""
    vitals = state.get("vitals") or {}
    names = {t.get("mac"): t.get("name") or t.get("mac") for t in state.get("tasters", [])}
    online, acked, missing = [], [], []
    for mac, name in names.items():
        v = vitals.get(mac) or {}
        if not v.get("ts") or now_ms - int(v["ts"]) > TASTER_ONLINE_MS:
            continue
        online.append(name)
        (acked if v.get("wv") == cfg["version"] else missing).append(name)
    return {"online": online, "acked": acked, "missing": missing}


def ready_for_pi(cfg: dict[str, Any], state: dict[str, Any], now_ms: int) -> bool:
    """Pi darf seinen Zugangspunkt erst umstellen, wenn alle online Taster bestaetigt haben."""
    if cfg.get("force"):
        return True
    st = taster_status(cfg, state, now_ms)
    return bool(st["online"]) and not st["missing"]


def applied_version() -> int:
    try:
        with open(APPLIED_FILE) as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def apply_to_pi(cfg: dict[str, Any], kind: str) -> Optional[str]:
    """Zugangspunkt dieses Pi umstellen. Fehlertext oder None. Muss als root laufen."""
    entry = cfg["wifi2"] if kind == "bad" else cfg["wifi1"]
    try:
        for cmd in (
            ["nmcli", "con", "modify", AP_CONNECTION, "802-11-wireless.ssid", entry["ssid"],
             "802-11-wireless-security.psk", entry["psk"]],
            ["nmcli", "con", "up", AP_CONNECTION],
        ):
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
            if res.returncode != 0:
                return (res.stderr or res.stdout).strip() or "nmcli fehlgeschlagen"
        with open(APPLIED_FILE, "w") as fh:
            fh.write(str(cfg["version"]))
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)
    return None
