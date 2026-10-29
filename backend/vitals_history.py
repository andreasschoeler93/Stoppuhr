"""Verlauf der Vitaldaten je Taster (Redis-Liste, begrenzt auf die letzten Stunden)."""
from __future__ import annotations

import json
from typing import Any, Final

KEY_PREFIX: Final[str] = "VITALS_HIST:"
KEEP_HOURS: Final[int] = 6
# Die Taster melden alle 10 s; etwas Reserve fuer schnellere Meldungen
MAX_POINTS: Final[int] = KEEP_HOURS * 360 + 60
FIELDS: Final[tuple[str, ...]] = ("battery", "vbat", "temp", "humidity", "rssi")


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
