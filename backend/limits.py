"""Einstellbare Grenzwerte fuer die Farben (gelb/rot) und Meldungen in der Oberflaeche."""
from __future__ import annotations

import math
from typing import Any, Final, Optional

# Je Messwert: Richtung ("low" = Wert darunter ist schlecht, "high" = darueber) und [gelb ab, rot ab]
DEFAULTS: Final[dict[str, dict[str, dict[str, Any]]]] = {
    "taster": {
        "battery": {"dir": "low", "values": [30, 15]},
        "vbat": {"dir": "low", "values": [3.5, 3.3]},
        "temp": {"dir": "high", "values": [45, 55]},
        "humidity": {"dir": "high", "values": [80, 90]},
        "rssi": {"dir": "low", "values": [-75, -85]},
    },
    "pi": {
        "cpu_temp": {"dir": "high", "values": [70, 80]},
        "cpu_percent": {"dir": "high", "values": [85, 95]},
        "mem_percent": {"dir": "high", "values": [85, 95]},
        "disk_percent": {"dir": "high", "values": [85, 95]},
    },
    "charger": {
        "temp": {"dir": "high", "values": [45, 60]},
        "humidity": {"dir": "high", "values": [80, 90]},
        "rssi": {"dir": "low", "values": [-75, -85]},
    },
    "finish": {
        "diff": {"dir": "high", "values": [0.5, 1]},
    },
}


def defaults() -> dict[str, dict[str, dict[str, Any]]]:
    return {g: {k: {"dir": r["dir"], "values": list(r["values"])} for k, r in rules.items()}
            for g, rules in DEFAULTS.items()}


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        num = float(str(value).replace(",", ".")) if isinstance(value, str) else float(value)
    except ValueError:
        return None
    return num if math.isfinite(num) and -1000 <= num <= 1000 else None


def merged(stored: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Standardwerte, ueberschrieben mit gueltigen gespeicherten Werten."""
    result = defaults()
    if not isinstance(stored, dict):
        return result
    for group, rules in result.items():
        saved_group = stored.get(group)
        if not isinstance(saved_group, dict):
            continue
        for key, rule in rules.items():
            saved = saved_group.get(key)
            values = saved.get("values") if isinstance(saved, dict) else None
            if isinstance(values, list) and len(values) == 2:
                warn, crit = _number(values[0]), _number(values[1])
                if warn is not None and crit is not None and _ordered(rule["dir"], warn, crit):
                    rule["values"] = [warn, crit]
    return result


def _ordered(direction: str, warn: float, crit: float) -> bool:
    return crit <= warn if direction == "low" else crit >= warn


def validate(payload: Any) -> tuple[Optional[dict[str, dict[str, dict[str, Any]]]], Optional[str]]:
    """Prueft eine komplette Eingabe; gibt (Grenzwerte, None) oder (None, Fehlertext) zurueck."""
    if not isinstance(payload, dict):
        return None, "Ungültige Eingabe."
    result = defaults()
    for group, rules in result.items():
        sent_group = payload.get(group)
        if not isinstance(sent_group, dict):
            continue
        for key, rule in rules.items():
            sent = sent_group.get(key)
            if sent is None:
                continue
            values = sent.get("values") if isinstance(sent, dict) else None
            if not isinstance(values, list) or len(values) != 2:
                return None, f"{group}/{key}: zwei Werte (gelb, rot) erwartet."
            warn, crit = _number(values[0]), _number(values[1])
            if warn is None or crit is None:
                return None, f"{group}/{key}: Zahlen zwischen -1000 und 1000 erwartet."
            if not _ordered(rule["dir"], warn, crit):
                order = "kleiner oder gleich" if rule["dir"] == "low" else "größer oder gleich"
                return None, f"{group}/{key}: Der rote Wert muss {order} dem gelben Wert sein."
            rule["values"] = [warn, crit]
    return result, None
