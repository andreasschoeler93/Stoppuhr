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
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final, Optional, TypedDict

import psutil
import redis
from flask import Flask, jsonify, render_template, request
from flask.typing import ResponseReturnValue


APP_VERSION: Final[str] = "0.4.3"
DEFAULT_PORT: Final[int] = 8000
EXIT_ERROR: Final[int] = 1
STATE_KEY: Final[str] = "STATE"
STARTER_KEY: Final[str] = "starter"


app = Flask(__name__, static_folder="static", template_folder="templates")
redis_store = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)


class Vital(TypedDict):
    battery: float
    temp: float
    humidity: float
    ts: int


class Taster(TypedDict):
    name: str
    mac: str
    ts: int
    stopwatch_ms: Optional[int]


class PressEvent(TypedDict):
    ts: int
    mac: str


@dataclass(slots=True)
class Startcard:
    startnummer: str
    name: str
    nachname: str
    vorname: str
    jahrgang: Optional[int]
    gliederung: str
    q_gld: str
    altersklasse: str
    geschlecht: str
    bemerkung: str
    disziplin: str
    wettkampf: str
    lauf: int
    bahn: int
    runde: str


class State(TypedDict):
    settings: dict[str, str]
    startcards: dict[str, Any]
    tasters: list[Taster]
    vitals: dict[str, Vital]
    current_run: int
    results: dict[int, Any]
    assignments: dict[str, Any]
    # Due to serialization, store run number always as string
    startcards_per_run: dict[str, list[Startcard]]
    triggers_per_run: dict[str, dict[str, list[PressEvent]]]  # Maps run to lane to PressEvent


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
        "tasters": [
            {"name": "A", "mac": "AA:BB:CC:DD:EE:00", "ts": 0, "stopwatch_ms": None},
            {"name": "B", "mac": "AA:BB:CC:DD:EE:01", "ts": 0, "stopwatch_ms": None},
            {"name": "C", "mac": "AA:BB:CC:DD:EE:02", "ts": 0, "stopwatch_ms": None},
            {"name": "D", "mac": "AA:BB:CC:DD:EE:03", "ts": 0, "stopwatch_ms": None},
            {"name": "E", "mac": "AA:BB:CC:DD:EE:04", "ts": 0, "stopwatch_ms": None},
            {"name": "F", "mac": "AA:BB:CC:DD:EE:05", "ts": 0, "stopwatch_ms": None},
        ],
        "results": {},
        "assignments": {"mapping": {}, "last_update_ts": None},
        "vitals": {},  # Maps the mac address to the vitals
        "startcards_per_run": defaultdict(list),
        "triggers_per_run": {},
        "current_run": 1,
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


@app.get("/simulator")
def simulator() -> str:
    return render_template("simulator.html", version=APP_VERSION)


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
    return jsonify(st["current_run"])


@app.get("/api/assignments")
def api_get_assignments():
    st = load_state()
    return jsonify(st["assignments"])


@app.get("/api/mapping")
def get_mapping():
    st = load_state()
    max_lane = st.get("startcards", {}).get("max_lane", 0)
    current_mapping = st.get("assignments", {}).get("mapping", {})

    tasters = st.get("tasters", [])
    mac_to_taster = {t.get("mac"): t for t in tasters}
    # Create a complete mapping for all lanes from 1 to max_lane
    full_mapping = {
        str(lane): mac_to_taster.get(current_mapping.get(str(lane)))
        for lane in range(1, max_lane + 1)
    }
    starter_taster = mac_to_taster.get(current_mapping.get(STARTER_KEY))

    # Get the set of MAC addresses that are already assigned to a lane
    mapped_macs = set(current_mapping.values())
    # Filter tasters whose MAC is not in the mapped_macs set
    unmapped_tasters = [t for t in tasters if t.get("mac") not in mapped_macs]

    return jsonify(
        {
            "mapping": full_mapping,
            "starter": starter_taster,
            "unmapped_taster": unmapped_tasters,
        }
    )


@app.get("/api/assignments/mapping")
def get_mapping_endpoint():
    """Returns the mapping for all available lanes based on max_lane."""
    st = load_state()
    max_lane = st.get("startcards", {}).get("max_lane", 0)
    current_mapping = st.get("assignments", {}).get("mapping", {})

    # Create a complete mapping for all lanes from 1 to max_lane
    full_mapping = {str(lane): current_mapping.get(str(lane)) for lane in range(1, max_lane + 1)}

    return jsonify({"ok": True, "max_lane": max_lane, "mapping": full_mapping})


@app.post("/api/assignments")
def api_post_assignments():
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    if "mapping" in payload:
        st["assignments"]["mapping"] = payload["mapping"]
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
    return jsonify({"ok": True, "assignments": st["assignments"]})


@app.post("/api/unassign")
def api_post_unassign():
    """Removes any MAC address assignment from a specific lane."""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    lane = payload.get("lane")

    if not lane:
        return jsonify({"ok": False, "error": "missing lane"}), 400

    lane_key = str(lane)
    current_mapping = st["assignments"]["mapping"]

    if lane_key in current_mapping:
        del current_mapping[lane_key]
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
        return jsonify({"ok": True, "mapping": current_mapping})

    return jsonify({"ok": True, "message": "lane was not assigned"})


@app.post("/api/assign")
def api_post_assign():
    """Assigns a MAC address to a specific lane."""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    mac = payload.get("mac")
    lane = payload.get("lane")

    if not mac or not lane:
        return jsonify({"ok": False, "error": "missing mac or lane"}), 400

    lane_key = str(lane)

    # Remove this MAC from any other lanes it might be assigned to
    current_mapping = st["assignments"]["mapping"]
    for lane, m in list(current_mapping.items()):
        if m == mac:
            del current_mapping[lane]

    # Assign the new MAC to the lane
    current_mapping[lane_key] = mac
    st["assignments"]["last_update_ts"] = now_ms()

    save_state(st)
    return jsonify({"ok": True, "mapping": current_mapping})


@app.get("/api/vitals")
def api_get_vitals():
    st = load_state()
    return jsonify(st["vitals"])


@app.post("/api/vitals")
def api_post_vitals():
    """Update Vitals from specified MAC address."""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    mac = payload.get("mac")
    if not mac:
        return jsonify({"ok": False, "error": "missing mac"}), 400
    new_vital: Vital = {
        "battery": payload.get("battery"),
        "temp": payload.get("temp"),
        "humidity": payload.get("humidity"),
        "ts": int(payload.get("ts", now_ms())),
    }
    st["vitals"][mac] = new_vital
    save_state(st)
    return jsonify({"ok": True, "vital": new_vital})


@app.get("/api/taster")
def api_get_taster():
    return jsonify({"tasters": load_state()["tasters"]})


@app.post("/api/taster")
def api_post_taster():
    """Register einen Taster"""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    mac = payload.get("mac")
    if not mac:
        return jsonify({"ok": False, "error": "missing mac"}), 400
    name = payload.get("name")
    if not name:
        return jsonify({"ok": False, "error": "missing name"}), 400
    entry: Taster = {
        "mac": str(mac),
        "name": str(name),
        "ts": int(payload.get("ts", now_ms())),
        "stopwatch_ms": payload.get("stopwatch_ms"),
    }
    st["tasters"].append(entry)

    save_state(st)
    return jsonify({"ok": True, "taster": entry})


@app.get("/api/startcards")
def api_load_startcards() -> tuple[ResponseReturnValue, int]:
    state = load_state()

    base_url = state["settings"].get("startcards_base_url", None)
    suffix = state["settings"].get("startcards_suffix", None)
    if not base_url:
        state["startcards"]["last_error"] = "base_url_missing"
        return jsonify({"ok": False, "error": "base_url_missing"}), 400

    if not suffix:
        state["startcards"]["last_error"] = "suffix_missing"
        return jsonify({"ok": False, "error": "suffix_missing"}), 400

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

        # Encoding-Erkennung (wichtig für Umlaute in Namen)
        text_csv = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                text_csv = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if text_csv is None:
            text_csv = raw.decode("latin-1", errors="replace")

        # CSV Verarbeitung mit Semikolon als Trenner
        f = io.StringIO(text_csv.strip())

        # 2. Use DictReader with semicolon delimiter
        reader = csv.DictReader(f, delimiter=";", quotechar='"')

        startcards = []
        runs = set()
        startcards_per_run = defaultdict(list)
        max_lane = 0

        for startcard in reader:
            # Clean startcard
            clean_startcard = {
                str(k).strip(): str(v).strip() for k, v in startcard.items() if k is not None
            }
            if not any(clean_startcard.values()):
                continue

            startcards.append(clean_startcard)
            # Determine the run number
            lauf = clean_startcard.get("Lauf")
            if lauf:
                runs.add(int(lauf))
                startcards_per_run[str(lauf)].append(clean_startcard)
            # Determine the highest lane number
            bahn = clean_startcard.get("Bahn")
            try:
                if bahn:
                    b_int = int(float(bahn))
                    if b_int > max_lane:
                        max_lane = b_int
            except (ValueError, TypeError):
                pass

        runs_sorted = sorted(list(runs), key=lambda x: int(x) if str(x).isdigit() else str(x))

        # 6. Update the global state
        state["startcards"].update(
            {
                "rows": startcards,
                # "startcards_per_run": startcards_per_run,
                "row_count": len(startcards),
                "last_fetch_ts": now_ms(),
                "last_error": None,
                "source_url": url,
                "max_lane": max_lane,
                "runs": runs_sorted,
                "loaded": True,
            }
        )
        state["startcards_per_run"] = startcards_per_run
        save_state(state)

        return jsonify(
            {
                "ok": True,
                "row_count": len(startcards),
                "rows": startcards,
                "startcards_per_run": startcards_per_run,
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


@app.get("/api/system-status")
def api_system_status():
    hostname = socket.gethostname()
    loadavg = os.getloadavg()
    cores = os.cpu_count()

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
            "load_avg": [
                float(loadavg[0] / cores),
                float(loadavg[1] / cores),
                float(loadavg[2] / cores),
            ],
            "cores": cores,
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


def _lane_for_mac(st: State, mac: str) -> Optional[str]:
    """
    Returns lane key ('1'..'N' or 'starter') for a given MAC based on current assignments.

    Args:
        st: Current state dictionary.
        mac: MAC address to look up.

    Returns:
        Lane key if found, otherwise None.
    """
    mapping = (st.get("assignments", {}) or {}).get("mapping", {}) or {}

    mac_norm = str(mac).strip()
    for lane_key, mapped_mac in mapping.items():
        if mapped_mac == mac_norm:
            return str(lane_key)
    return None


@app.get("/taster-buttons")
def taster_buttons() -> str:
    return render_template("taster-buttons.html", version=APP_VERSION)


@app.post("/api/triggers")
def api_post_triggers():
    """
    Records a taster press for the CURRENT run.

    Payload:
      { "mac": "AA:BB:...", "ts": 123(optional) }

    Response:
      { ok: true, press: {ts, run, mac} }
    """
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}

    mac = payload.get("mac")
    if not mac:
        return jsonify({"ok": False, "error": "missing mac"}), 400

    current_run = st.get("current_run")
    if current_run is None or str(current_run).strip() == "":
        return jsonify({"ok": False, "error": "no current_run selected"}), 400

    ts_val = int(payload.get("ts", now_ms()))

    mac_norm = str(mac).strip()
    lane = _lane_for_mac(st, mac_norm)

    if lane is None:
        return jsonify({"ok": False, "error": f"no lane found for mac {mac_norm}"}), 400

    presses = st.get("triggers_per_run", dict)
    presses.setdefault(str(current_run), {})
    presses[str(current_run)].setdefault(lane, [])
    # Abort press if the run has not been started yet.
    if lane != STARTER_KEY and not any(p == STARTER_KEY for p in presses[str(current_run)].keys()):
        return jsonify({"ok": False, "error": "Run has not started yet."}), 400
    # Abort double press
    if presses[str(current_run)][lane]:
        return jsonify({"ok": False, "error": "Double press detected."}), 400

    press: PressEvent = {
        "ts": ts_val,
        "mac": mac_norm,
    }

    presses[str(current_run)][lane].append(press)
    # Check, if for all lanes presses have been received
    if not (
        set([v["Bahn"] for v in st["startcards_per_run"][str(current_run)]])
        - set(presses[str(current_run)].keys())
    ):
        print(f"All lanes have been pressed: start run: {int(current_run) + 1}")
        # Increase run number
        st["current_run"] = int(current_run) + 1
    save_state(st)
    return jsonify({"ok": True, "press": press})


@app.get("/tasters")
def tasters_page() -> str:
    return render_template("tasters.html", version=APP_VERSION)


def main():
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
