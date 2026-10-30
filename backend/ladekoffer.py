"""Status des Ladekoffers: Die Ladeplatine meldet per POST /api/charger, die Oberflaeche liest ihn."""
from __future__ import annotations

import json
import threading
from typing import Any, Final, Optional

KEY: Final[str] = "CHARGER_STATUS"
SLOT_COUNT: Final[int] = 10
# Die Platine sendet alle 5 s; danach gilt sie als offline
OFFLINE_AFTER_MS: Final[int] = 30_000
LIGHTS: Final[frozenset[str]] = frozenset({"off", "green", "yellow", "yellow_blink", "red", "red_blink"})

# Letzter Stand im Speicher, falls Redis gerade nicht schreibbar ist (z. B. Kopie im Zwei-Pi-Betrieb)
_memory: Optional[dict[str, Any]] = None
_lock = threading.Lock()


def _num(value: Any, lo: float, hi: float) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or not lo <= value <= hi:  # NaN oder ausserhalb des Bereichs
        return None
    return float(value)


def _int(value: Any, lo: int, hi: int) -> Optional[int]:
    num = _num(value, lo, hi)
    return None if num is None else int(num)


def _text(value: Any, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def sanitize(payload: Any) -> Optional[dict[str, Any]]:
    """Prueft die Meldung der Platine und gibt nur bekannte, begrenzte Felder zurueck."""
    if not isinstance(payload, dict) or not isinstance(payload.get("slots"), list):
        return None
    slots: dict[int, dict[str, Any]] = {}
    for raw in payload["slots"]:
        if not isinstance(raw, dict):
            continue
        n = _int(raw.get("n"), 1, SLOT_COUNT)
        if n is None:
            continue
        slots[n] = {
            "n": n,
            "present": raw.get("present") is True,
            "charging": raw.get("charging") is True,
            "full": raw.get("full") is True,
            "fault": raw.get("fault") is True,
            "vbat": _num(raw.get("vbat"), 0, 10),
        }
    light = payload.get("light")
    return {
        "mac": _text(payload.get("mac"), 32),
        "fw": _text(payload.get("fw"), 16),
        "uptime_s": _int(payload.get("uptime_s"), 0, 10**9),
        "rssi": _int(payload.get("rssi"), -150, 0),
        "temp": _num(payload.get("temp"), -50, 150),
        "humidity": _num(payload.get("humidity"), 0, 100),
        "aht_ok": payload.get("aht_ok") is True,
        "temp_alarm": payload.get("temp_alarm") is True,
        "i2c_ok": payload.get("i2c_ok") is True,
        "light": light if light in LIGHTS else "off",
        "fault": payload.get("fault") is True,
        "muted": payload.get("muted") is True,
        "slots": [slots[n] for n in sorted(slots)],
    }


def save(r: Any, status: dict[str, Any]) -> None:
    """Merkt den Stand im Speicher und (wenn moeglich) in Redis."""
    global _memory
    with _lock:
        _memory = status
    try:
        r.set(KEY, json.dumps(status, separators=(",", ":")))
    except Exception:  # noqa: BLE001
        pass


def load(r: Any) -> Optional[dict[str, Any]]:
    """Neuester bekannter Stand aus Speicher und Redis."""
    with _lock:
        best = _memory
    try:
        raw = r.get(KEY)
        stored = json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        stored = None
    if isinstance(stored, dict) and (best is None or stored.get("ts", 0) > best.get("ts", 0)):
        best = stored
    return best


def reset_memory() -> None:
    global _memory
    with _lock:
        _memory = None


def _age_text(age_ms: int) -> str:
    minutes = age_ms // 60_000
    if minutes < 1:
        return "weniger als 1 Minute"
    if minutes < 60:
        return f"{minutes} Min."
    return f"{minutes // 60} Std. {minutes % 60} Min."


def _comma(value: float, dec: int = 1) -> str:
    return f"{value:.{dec}f}".replace(".", ",")


def evaluate(status: Optional[dict[str, Any]], now_ms: int) -> dict[str, Any]:
    """Leitet aus dem Stand Zustand und Statusmeldungen ab (level: error, warn, info, ok)."""
    if not status:
        return {"known": False, "online": False, "state": "unbekannt", "status": None, "messages": [],
                "counts": {"present": 0, "charging": 0, "full": 0, "missing": []}}
    slots = {s["n"]: s for s in status.get("slots", [])}
    present = [n for n, s in slots.items() if s["present"]]
    charging = [n for n, s in slots.items() if s["charging"]]
    full = [n for n, s in slots.items() if s["full"]]
    missing = [n for n in range(1, SLOT_COUNT + 1) if n not in present]
    age = max(0, now_ms - int(status.get("ts") or 0))
    online = age <= OFFLINE_AFTER_MS
    messages: list[dict[str, str]] = []

    if not online:
        state = "offline"
        messages.append({"level": "warn", "text": f"Ladekoffer meldet sich nicht (zuletzt vor {_age_text(age)})."})
    else:
        if status.get("temp_alarm"):
            temp = status.get("temp")
            extra = f" ({_comma(temp)} °C)" if temp is not None else ""
            messages.append({"level": "error", "text": f"Übertemperatur im Ladekoffer{extra}."})
        if not status.get("i2c_ok"):
            messages.append({"level": "error", "text": "Ladeplatine: Baustein MCP23017 antwortet nicht, Ladestatus unsicher."})
        for n in sorted(slots):
            if slots[n]["fault"]:
                vbat = slots[n].get("vbat")
                extra = f" ({_comma(vbat, 2)} V)" if vbat is not None else ""
                messages.append({"level": "error", "text": f"Platz {n}: Akkuspannung zu hoch{extra}."})
        if not status.get("aht_ok") and not status.get("temp_alarm"):
            messages.append({"level": "warn", "text": "Temperatursensor (AHT20) im Ladekoffer fehlt oder liefert nichts."})

        has_error = any(m["level"] == "error" for m in messages)
        if has_error or status.get("fault"):
            state = "fehler"
        elif charging:
            state = "laedt"
        elif len(present) == SLOT_COUNT and len(full) == SLOT_COUNT:
            state = "bereit"
        else:
            state = "teilweise"

        if len(present) == SLOT_COUNT and len(full) == SLOT_COUNT and not has_error:
            messages.append({"level": "ok", "text": f"Alle {SLOT_COUNT} Taster sind geladen."})
        else:
            if missing:
                messages.append({"level": "info", "text": "Nicht im Koffer: Platz " + ", ".join(map(str, missing)) + "."})
            if charging:
                messages.append({"level": "info", "text": f"{len(charging)} Taster laden noch: Platz " + ", ".join(map(str, charging)) + "."})
            idle = [n for n in present if n not in full and n not in charging]
            if idle:
                messages.append({"level": "info", "text": "Eingesetzt, aber nicht voll und lädt nicht: Platz " + ", ".join(map(str, idle)) + "."})

    return {
        "known": True,
        "online": online,
        "state": state,
        "age_ms": age,
        "status": status,
        "messages": messages,
        "counts": {"present": len(present), "charging": len(charging), "full": len(full), "missing": missing},
    }
