# ----------------------------------------
# Stoppuhr Webserver
# Version: v0.4.3
# Status: stable-beta
# ----------------------------------------


import csv
import io
import json
import os
import re
import socket
import struct
import time
import urllib.request
from typing import Any, Final, Optional, TypedDict

import psutil
import redis
from flask import Flask, jsonify, render_template, request
from flask.typing import ResponseReturnValue


APP_VERSION: Final[str] = "0.4.3"
DEFAULT_PORT: Final[int] = 8000
EXIT_ERROR: Final[int] = 1
STATE_KEY: Final[str] = "STATE"


app = Flask(__name__, static_folder="static", template_folder="templates")
redis_store = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)


class Vital(TypedDict):
    taster: str
    battery: float
    temp: float
    humidity: float
    ts: int


class Trigger(TypedDict):
    taster: str
    ts: int
    stopwatch_ms: Optional[int]
    run_id: Optional[str]


class State(TypedDict):
    settings: dict[str, str]
    startcards: dict[str, Any]
    tasters: dict[str, Any]
    vitals: list[dict[str, Any]]  # list[Vital]
    triggers: list[Trigger]
    runs: dict[str, Any]
    assignments: dict[str, Any]


def _default_state() -> State:
    return {
        "settings": {
            "startcards_base_url": "",
            "startcards_suffix": "/export/CSV/Startkarten.csv",
        },
        "startcards": {
            "loaded": False,
            "last_fetch_ts": None,
            "row_count": 0,
            "rows": [],
            "last_error": None,
            "url": None,
        },
        "tasters": {
            "items": [],
            "last_refresh_ts": None,
        },
        "runs": {"current_run": None, "runs": []},
        "assignments": {"mapping": {}, "last_update_ts": None},
        "vitals": [],
        "triggers": [],
    }


def load_state() -> State:
    state = redis_store.get(STATE_KEY)
    if state is None:
        state = _default_state()
        save_state(state)
    else:
        state = json.loads(state)
    return state


def save_state(state: State) -> None:
    redis_store.set(STATE_KEY, json.dumps(state))


def now_ms() -> int:
    return int(time.time() * 1000)


@app.get("/")
def index() -> str:
    return render_template("index.html", version=APP_VERSION)


@app.get("/api/version")
def api_version() -> dict[str, str]:
    return {"version": str(APP_VERSION), "status": "stable-beta"}


@app.get("/api/settings")
def api_get_settings() -> ResponseReturnValue:
    st = load_state()
    return jsonify(st.get("settings", {}))


@app.post("/api/settings")
def api_set_settings() -> ResponseReturnValue:
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    settings = st.get("settings", {})
    for k in ["startcards_base_url", "startcards_suffix"]:
        if k in payload:
            settings[k] = str(payload[k] or "")
    st["settings"] = settings
    save_state(st)
    return jsonify({"ok": True, "settings": settings})


@app.get("/api/runs")
def api_get_runs():
    st = load_state()
    return jsonify(st["runs"])


@app.post("/api/runs")
def api_post_runs():
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    if "current_run" in payload:
        st["runs"]["current_run"] = payload["current_run"]
    if "run" in payload:
        st["runs"]["runs"].append(payload["run"])
    save_state(st)
    return jsonify({"ok": True, "runs": st["runs"]})


@app.get("/api/assignments")
def api_get_assignments():
    st = load_state()
    return jsonify(st["assignments"])


@app.post("/api/assignments")
def api_post_assignments():
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    if "mapping" in payload:
        st["assignments"]["mapping"] = payload["mapping"]
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
    return jsonify({"ok": True, "assignments": st["assignments"]})


@app.get("/api/vitals")
def api_get_vitals():
    st = load_state()
    return jsonify(st["vitals"])


@app.post("/api/vitals")
def api_post_vitals():
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    entry = {}
    for k in ("taster", "battery", "temp", "humidity"):
        if k in payload:
            entry[k] = payload[k]
    entry["ts"] = int(payload.get("ts", now_ms()))
    st["vitals"].append(entry)
    save_state(st)
    return jsonify({"ok": True, "vital": entry})


@app.get("/api/triggers")
def api_get_triggers():
    st = load_state()
    return jsonify(st["triggers"])


@app.post("/api/triggers")
def api_post_triggers():
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    taster = payload.get("taster")
    if not taster:
        return jsonify({"ok": False, "error": "missing taster"}), 400
    entry: Trigger = {
        "taster": str(taster),
        "ts": int(payload.get("ts", now_ms())),
        "stopwatch_ms": payload.get("stopwatch_ms"),
        "run_id": payload.get("run_id"),
    }
    st["triggers"].append(entry)
    # backward compatibility: keep tasters.items
    if "tasters" not in st:
        st["tasters"] = {"items": [], "last_refresh_ts": None}
    st["tasters"]["items"].append({"taster": entry["taster"], "ts": entry["ts"]})
    save_state(st)
    return jsonify({"ok": True, "trigger": entry})


# --- END ---


@app.post("/api/startcards/reload")
def api_reload_startcards() -> tuple[ResponseReturnValue, int]:
    """
    Manuelles Nachladen der Startkarten von der Auswertungssoftware.
    - Kein Auto-Refresh (Robustheit): wird nur auf Nutzeraktion geladen.
    - Basis-URL + Suffix werden aus Settings genommen (oder können im Request überschrieben werden).
    """
    state = load_state()
    data = request.get_json(silent=True) or {}

    base_url = str(data.get("base_url", state["settings"].get("startcards_base_url", ""))).strip()
    suffix = str(
        data.get(
            "suffix",
            state["settings"].get("startcards_suffix", "/export/CSV/Startkarten.csv"),
        )
    ).strip()

    # Settings aktualisieren, damit UI "übernimmt"
    state["settings"]["startcards_base_url"] = base_url
    state["settings"]["startcards_suffix"] = suffix
    save_state(state)

    if not base_url:
        state["startcards"]["last_error"] = "base_url_missing"
        save_state(state)
        return jsonify({"ok": False, "error": "base_url_missing"}), 400

    # Normalisierung: '192.168.x.x:8082' -> 'http://192.168.x.x:8082'
    if not re.match(r"^https?://", base_url, re.IGNORECASE):
        base_url = "http://" + base_url

    # URL zusammensetzen
    try:
        # ensure suffix begins with /
        if not suffix.startswith("/"):
            suffix = "/" + suffix
        url = base_url.rstrip("/") + suffix
    except Exception:
        url = base_url.rstrip("/") + suffix

    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"stoppuhr/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()

        # CSV ist i.d.R. Windows-1252/Latin-1 oder UTF-8; wir versuchen mehrere.
        text_csv = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text_csv = raw.decode(enc)
                break
            except Exception:
                continue
        if text_csv is None:
            text_csv = raw.decode("latin-1", errors="replace")

        # Semikolon-separiert, Felder evtl. in Anführungszeichen
        f = io.StringIO(text_csv)
        reader = csv.DictReader(f, delimiter=";")
        rows = []
        for row in reader:
            # Normalize keys (strip BOM/whitespace)
            clean = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            if any(clean.values()):
                rows.append(clean)

        # Derive runs + max_lane
        max_lane = 0
        runs = set()
        for r in rows:
            lauf = (r.get("Lauf") or "").strip()
            if lauf != "":
                runs.add(lauf)
            bahn = (r.get("Bahn") or "").strip()
            try:
                b = int(float(bahn)) if bahn != "" else 0
            except Exception:
                b = 0
            if b > max_lane:
                max_lane = b

        runs_sorted = sorted(runs, key=lambda x: int(x) if str(x).isdigit() else str(x))

        state["startcards"]["rows"] = rows
        state["startcards"]["last_fetch_ts"] = int(time.time() * 1000)
        state["startcards"]["last_error"] = None
        state["startcards"]["source_url"] = url
        state["startcards"]["max_lane"] = max_lane
        state["startcards"]["runs"] = runs_sorted
        save_state(state)

        return jsonify(
            {
                "ok": True,
                "row_count": len(rows),
                "source_url": url,
                "max_lane": max_lane,
                "runs": runs_sorted,
                "last_fetch_ts": state["startcards"]["last_fetch_ts"],
            }
        ), 200
    except Exception as e:
        state["startcards"]["last_error"] = f"{type(e).__name__}: {e}"
        state["startcards"]["last_fetch_ts"] = int(time.time() * 1000)
        state["startcards"]["source_url"] = url
        save_state(state)
        return jsonify(
            {"ok": False, "error": state["startcards"]["last_error"], "source_url": url}
        ), 500


@app.get("/api/startcards")
def api_get_startcards():
    st = load_state()
    return jsonify(st.get("startcards", {}))


@app.get("/api/taster-list")
def api_taster_list():
    """v0.4.1: Demo/Stub."""
    st = load_state()
    tasters = st.get("tasters", {})
    items = tasters.get("items", [])

    if not items:
        demo = []
        for i, letter in enumerate(["A", "B", "C", "D", "E"]):
            demo.append(
                {
                    "mac": f"AA:BB:CC:DD:EE:{i:02X}",
                    "letter": letter,
                    "role": "bahn",
                    "lane": i + 1,
                    "last_seen_ms": now_ms() - (i * 12000),
                    "last_event_type": "heartbeat",
                    "last_battery_percent": 90 - i * 5,
                    "last_rssi_dbm": -50 - i * 3,
                    "last_temp_c": 25.0 + i * 0.2,
                    "last_humidity_rel": 55.0 + i * 0.5,
                    "time_correction_ms": 0,
                    "diff_thresholds_ms": {"ok": 200, "warn": 500},
                    "start_finish_combo": False,
                }
            )
        items = demo
        tasters["items"] = items
        tasters["last_refresh_ts"] = now_ms()
        st["tasters"] = tasters
        save_state(st)

    return jsonify(
        {
            "ok": True,
            "tasters": items,
            "last_refresh_ts": tasters.get("last_refresh_ts"),
        }
    )


@app.get("/api/system-status")
def api_system_status():
    hostname = socket.gethostname()
    loadavg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)

    cpu_percent = psutil.cpu_percent(interval=None)

    virtual_mem = psutil.virtual_memory()
    mem = {
        "total": virtual_mem.total,
        "used": virtual_mem.used,
        "free": virtual_mem.available,  # 'available' is usually better than 'free' on Linux
        "percent": virtual_mem.percent,
    }

    disk_usage = psutil.disk_usage("/")
    disk = {
        "total": disk_usage.total,
        "used": disk_usage.used,
        "free": disk_usage.free,
        "percent": disk_usage.percent,
    }

    return jsonify(
        {
            "hostname": hostname,
            "load_avg": [float(loadavg[0]), float(loadavg[1]), float(loadavg[2])],
            "cpu_percent": cpu_percent,
            "mem": mem,
            "disk": disk,
            "services": {"stoppuhr": "active"},
        }
    )


@app.get("/api/network-status")
def api_network_status():
    # Get default gateway
    default_gateway = None
    try:
        with open("/proc/net/route") as fh:
            for line in fh:
                fields = line.strip().split()
                if len(fields) > 3 and fields[1] == "00000000" and int(fields[3], 16) & 2:
                    default_gateway = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
                    break
    except Exception:
        pass

    # Get DNS servers
    dns_servers = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) > 1:
                        dns_servers.append(parts[1])
    except Exception:
        pass

    # Get interfaces
    interfaces = {}
    net_addrs = psutil.net_if_addrs()
    net_stats = psutil.net_if_stats()
    for ifn in net_addrs:
        addrs = net_addrs[ifn]
        stats = net_stats.get(ifn)
        mac = None
        ipv4 = None
        ipv6 = None
        state = None
        if stats:
            state = "up" if stats.isup else "down"
        for addr in addrs:
            if addr.family == psutil.AF_LINK:
                mac = addr.address
            elif addr.family == socket.AF_INET and not ipv4:
                if addr.netmask:
                    mask_bits = bin(int.from_bytes(socket.inet_aton(addr.netmask), "big")).count(
                        "1"
                    )
                    ipv4 = f"{addr.address}/{mask_bits}"
            elif addr.family == socket.AF_INET6 and not ipv6:
                if addr.netmask:
                    mask_bytes = socket.inet_pton(socket.AF_INET6, addr.netmask)
                    mask_bits = int.from_bytes(mask_bytes, "big").bit_count()
                    ipv6 = f"{addr.address}/{mask_bits}"
        interfaces[ifn] = {
            "mac": mac,
            "state": state,
            "ipv4": ipv4,
            "ipv6": ipv6,
        }

    return jsonify(
        {
            "default_gateway": default_gateway,
            "dns_servers": dns_servers,
            "interfaces": interfaces,
        }
    )


def main():
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
