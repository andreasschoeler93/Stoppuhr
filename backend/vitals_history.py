"""Verlauf der Vitaldaten je Taster (Redis-Liste, begrenzt auf die letzten Stunden)."""
from __future__ import annotations

import json
from typing import Any, Final

KEY_PREFIX: Final[str] = "VITALS_HIST:"
STARTS_KEY: Final[str] = "RUN_STARTS"
KEEP_HOURS: Final[int] = 6
# Die Taster melden alle 10 s; etwas Reserve fuer schnellere Meldungen
MAX_POINTS: Final[int] = KEEP_HOURS * 360 + 60
FIELDS: Final[tuple[str, ...]] = ("battery", "vbat", "temp", "humidity", "rssi")
PI_PREFIX: Final[str] = "PI_HIST:"
PI_FIELDS: Final[tuple[str, ...]] = ("cpu_temp", "cpu_percent", "mem_percent")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def add(r: Any, mac: str, ts_ms: int, vital: dict[str, Any]) -> None:
    """Haengt einen Messpunkt an; Fehler duerfen die Vitalmeldung nie stoeren."""
    try:
        point = [ts_ms] + [_num(vital.get(f)) for f in FIELDS]
        key = KEY_PREFIX + mac
        pipe = r.pipeline()
        pipe.rpush(key, json.dumps(point, separators=(",", ":")))
        pipe.ltrim(key, -MAX_POINTS, -1)
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass


LABELS_KEY: Final[str] = "VITALS_LABELS"


def set_label(r: Any, mac: str, letter: Any) -> None:
    """Merkt sich den Buchstaben je MAC, damit der Verlauf auch nach Wettkampfende beschriftet bleibt."""
    if not letter:
        return
    try:
        r.hset(LABELS_KEY, mac, str(letter))
    except Exception:  # noqa: BLE001
        pass


def known(r: Any, since_ms: int = 0) -> list[dict[str, Any]]:
    """Alle Taster mit Verlauf im Zeitraum (auch solche, die gerade nicht angemeldet sind)."""
    out: list[dict[str, Any]] = []
    try:
        labels = r.hgetall(LABELS_KEY) or {}
        for key in r.scan_iter(match=KEY_PREFIX + "*"):
            last = r.lindex(key, -1)
            if last is None or json.loads(last)[0] < since_ms:
                continue
            mac = key[len(KEY_PREFIX):]
            out.append({"mac": mac, "letter": labels.get(mac)})
    except Exception:  # noqa: BLE001
        return []
    return sorted(out, key=lambda e: (e["letter"] is None, str(e["letter"] or ""), e["mac"]))


def history(r: Any, mac: str, since_ms: int = 0) -> list[list[Any]]:
    try:
        raw = r.lrange(KEY_PREFIX + mac, 0, -1)
    except Exception:  # noqa: BLE001
        return []
    points: list[list[Any]] = []
    for item in raw:
        try:
            p = json.loads(item)
        except ValueError:
            continue
        if isinstance(p, list) and len(p) == len(FIELDS) + 1 and p[0] >= since_ms:
            points.append(p)
    return points


def add_pi(r: Any, name: str, ts_ms: int, node: dict[str, Any]) -> None:
    """Messpunkt eines Pi (CPU-Temperatur, CPU-Last, Arbeitsspeicher)."""
    try:
        point = [ts_ms] + [_num(node.get(f)) for f in PI_FIELDS]
        key = PI_PREFIX + name
        pipe = r.pipeline()
        pipe.rpush(key, json.dumps(point, separators=(",", ":")))
        pipe.ltrim(key, -MAX_POINTS, -1)
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass


def history_pi(r: Any, name: str, since_ms: int = 0) -> list[list[Any]]:
    try:
        raw = r.lrange(PI_PREFIX + name, 0, -1)
    except Exception:  # noqa: BLE001
        return []
    points: list[list[Any]] = []
    for item in raw:
        try:
            p = json.loads(item)
        except ValueError:
            continue
        if isinstance(p, list) and len(p) == len(PI_FIELDS) + 1 and p[0] >= since_ms:
            points.append(p)
    return points


def add_start(r: Any, ts_ms: int, run_key: str) -> None:
    """Merkt sich einen Laufstart (senkrechte Linie im Diagramm)."""
    try:
        pipe = r.pipeline()
        pipe.rpush(STARTS_KEY, json.dumps([ts_ms, run_key], separators=(",", ":")))
        pipe.ltrim(STARTS_KEY, -200, -1)
        pipe.execute()
    except Exception:  # noqa: BLE001
        pass


def starts(r: Any, since_ms: int = 0) -> list[list[Any]]:
    try:
        raw = r.lrange(STARTS_KEY, 0, -1)
    except Exception:  # noqa: BLE001
        return []
    out: list[list[Any]] = []
    for item in raw:
        try:
            p = json.loads(item)
        except ValueError:
            continue
        if isinstance(p, list) and len(p) == 2 and p[0] >= since_ms:
            out.append(p)
    return out
