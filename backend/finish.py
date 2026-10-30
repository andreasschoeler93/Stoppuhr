"""Zieleinlauf: Druecke sammeln und den Bahnzeiten zuordnen (reine Logik ohne Flask/Redis)."""

from typing import Any

FINISH_KEY = "ziel"
# Ein Zieleinlauf-Druck darf hoechstens so weit von der Bahnzeit entfernt sein, um automatisch zugeordnet zu werden
MATCH_WINDOW_MS = 3000
# Prellen des Tasters: Druecke in so kurzem Abstand zaehlen als einer
DEBOUNCE_MS = 500


def finish_times(starter_ts: int, presses: list[dict[str, Any]]) -> list[int]:
    """Zeit seit dem Start (ms) je Zieleinlauf-Druck, in Reihenfolge der Druecke."""
    return [int(p["ts"]) - starter_ts for p in presses]


def match(
    lane_times: dict[str, int],
    times: list[int],
    manual: dict[str, int],
) -> dict[str, dict[str, Any]]:
    """
    Ordnet Zieleinlauf-Zeiten den Bahnen zu.

    Args:
        lane_times: Gestoppte Zeit (ms) je Bahn, Bahnen ohne Zeit fehlen. Zeiten, die selbst aus dem
            Zieleinlauf stammen, gehoeren nicht hinein (sie sind ueber ``manual`` zugeordnet).
        times: Zeiten (ms) der Zieleinlauf-Druecke.
        manual: Haendliche Zuordnung Bahn -> Index in ``times``.

    Returns:
        Bahn -> {"index", "manual", "delta_ms"}; delta_ms = Zieleinlauf-Zeit minus Bahnzeit
        (None, wenn die Bahn keine eigene Zeit hat).
    """
    result: dict[str, dict[str, Any]] = {}
    used: set[int] = set()
    for lane, index in manual.items():
        if isinstance(index, int) and 0 <= index < len(times) and index not in used:
            lane_time = lane_times.get(lane)
            result[lane] = {
                "index": index,
                "manual": True,
                "delta_ms": None if lane_time is None else times[index] - lane_time,
            }
            used.add(index)

    # Rest automatisch: kleinster Abstand zuerst
    pairs = sorted(
        (abs(t - lt), lane, index)
        for lane, lt in lane_times.items()
        if lane not in result
        for index, t in enumerate(times)
        if index not in used
    )
    for distance, lane, index in pairs:
        if distance > MATCH_WINDOW_MS:
            break
        if lane in result or index in used:
            continue
        result[lane] = {"index": index, "manual": False, "delta_ms": times[index] - lane_times[lane]}
        used.add(index)
    return result


def unassigned(times: list[int], matches: dict[str, dict[str, Any]]) -> list[int]:
    """Indizes der Zieleinlauf-Druecke, die keiner Bahn zugeordnet sind."""
    used = {m["index"] for m in matches.values()}
    return [i for i in range(len(times)) if i not in used]
