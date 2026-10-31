"""Archiv abgeschlossener Wettkaempfe (Redis): Ergebnisse, Rohdaten und Vitalverlauf je Wettkampf."""
from __future__ import annotations

import json
from typing import Any, Final, Optional

INDEX_KEY: Final[str] = "ARCHIVE_INDEX"  # Hash: id -> Kurzinfo (JSON)
DATA_PREFIX: Final[str] = "ARCHIVE:"


def save(r: Any, competition: dict[str, Any]) -> None:
    """Speichert den Wettkampf (competition["id"] muss gesetzt sein) und traegt ihn in den Index ein."""
    cid = str(competition["id"])
    meta = {
        "id": cid,
        "name": competition.get("name", ""),
        "ended_ts": competition.get("ended_ts"),
        "heats": len(competition.get("heats") or []),
        "runs": len({h[0] for h in competition.get("heats") or []}),
    }
    pipe = r.pipeline()
    pipe.set(DATA_PREFIX + cid, json.dumps(competition, separators=(",", ":")))
    pipe.hset(INDEX_KEY, cid, json.dumps(meta, separators=(",", ":")))
    pipe.execute()


def list_all(r: Any) -> list[dict[str, Any]]:
    """Kurzinfos, neueste zuerst."""
    items: list[dict[str, Any]] = []
    for raw in (r.hgetall(INDEX_KEY) or {}).values():
        try:
            items.append(json.loads(raw))
        except ValueError:
            continue
    return sorted(items, key=lambda m: m.get("ended_ts") or 0, reverse=True)


def load(r: Any, cid: str) -> Optional[dict[str, Any]]:
    raw = r.get(DATA_PREFIX + str(cid))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def delete(r: Any, cid: str) -> bool:
    pipe = r.pipeline()
    pipe.delete(DATA_PREFIX + str(cid))
    pipe.hdel(INDEX_KEY, str(cid))
    removed = pipe.execute()
    return bool(removed[1])
