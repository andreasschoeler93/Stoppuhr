# ----------------------------------------
# Stoppuhr Webserver
# Version: v0.4.3
# Status: stable-beta
# ----------------------------------------


import csv
import io
import json
import logging
import os
import re
import socket
import struct
import time
import unicodedata
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final, Optional, TypedDict

import psutil
import redis
from flask import Flask, Response, abort, jsonify, render_template, request
from flask.typing import ResponseReturnValue
from xml_writer import create_xml_heats


APP_VERSION: Final[str] = "0.4.3"
DEFAULT_PORT: Final[int] = 1999  # Since JAuswertung expected this port
EXIT_ERROR: Final[int] = 1
STATE_KEY: Final[str] = "STATE"
STARTER_KEY: Final[str] = "starter"
CLOCK_OFFSET_MIN_MS: Final[int] = 250
HEATS_XML_PATH: Final[str] = "/app/results/heats.xml"


app = Flask(__name__, static_folder="static", template_folder="templates")
redis_store = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)
logger = logging.getLogger(__name__)


class Vital(TypedDict):
    battery: float
    temp: float
    humidity: float
    ts: int
    vbat: Optional[float]
    rssi: Optional[int]
    fw: Optional[str]
    uptime_s: Optional[int]


TASTER_LETTERS = "ABCDEFGHIJ"


class Taster(TypedDict, total=False):
    letter: Optional[str]
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
    triggers_per_run: dict[str, dict[str, PressEvent]]  # Maps run to lane to PressEvent


def _default_state() -> State:
    return {
        "settings": {
            "startcards_base_url": "",
            "startcards_suffix": "/export/CSV/Startkarten.csv",
            "auto_next_run_s": "10",
            "stop_lockout_s": "5",
        },
        "startcards": {
            "loaded": False,
            "last_fetch_ts": None,
            "row_count": 0,
            "rows": [],
            "last_error": None,
            "url": None,
        },
        "tasters": [],  # Taster melden sich selbst per POST /api/taster an
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


def _auto_next_delay_ms(st: State) -> int:
    """Wartezeit bis zum automatischen Wechsel in den naechsten Lauf (Einstellung, Standard 10 s)."""
    try:
        return max(0, int(st.get("settings", {}).get("auto_next_run_s", 10))) * 1000
    except (TypeError, ValueError):
        return 10_000


def _stop_lockout_ms(st: State) -> int:
    """Stopp-Sperre nach dem Start in ms (Einstellung, Standard 5 s, 0 = aus)."""
    try:
        return max(0, int(st.get("settings", {}).get("stop_lockout_s", 5))) * 1000
    except (TypeError, ValueError):
        return 5_000


def _advance_run(st: State) -> None:
    st["current_run"] = int(st.get("current_run") or 0) + 1
    st["run_finished_ts"] = None
    save_state(st)


def _maybe_advance_run(st: State) -> None:
    """Springt in den naechsten Lauf, wenn der abgeschlossene Lauf lange genug angezeigt wurde."""
    finished = st.get("run_finished_ts")
    if finished is not None and now_ms() - int(finished) >= _auto_next_delay_ms(st):
        _advance_run(st)


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
    for key in ("auto_next_run_s", "stop_lockout_s"):
        if key in payload:
            try:
                settings[key] = str(max(0, int(payload[key])))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": f"{key} must be a number"}), 400
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


TASTER_ONLINE_TIMEOUT_MS: Final[int] = 30_000


def _taster_with_vitals(taster: Taster, vitals: dict[str, Vital]) -> dict[str, Any]:
    """Taster-Eintrag um Vitaldaten und Online-Status (anhand des letzten Vitals-ts) ergaenzen."""
    v = vitals.get(taster.get("mac")) or {}
    last_seen = v.get("ts")
    return {
        **taster,
        "battery": v.get("battery"),
        "rssi": v.get("rssi"),
        "vbat": v.get("vbat"),
        "temp": v.get("temp"),
        "humidity": v.get("humidity"),
        "fw": v.get("fw"),
        "last_seen_ts": last_seen,
        "online": bool(last_seen) and now_ms() - int(last_seen) <= TASTER_ONLINE_TIMEOUT_MS,
    }


@app.get("/api/mapping")
def get_mapping():
    st = load_state()
    max_lane = st.get("startcards", {}).get("max_lane", 0)
    current_mapping = st.get("assignments", {}).get("mapping", {})

    tasters = [_taster_with_vitals(t, st.get("vitals", {})) for t in st.get("tasters", [])]
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
        # Der Server-Zeitstempel zaehlt, die Uhr des Tasters ist beim Start evtl. nicht synchron
        "ts": now_ms(),
        "vbat": payload.get("vbat"),
        "rssi": payload.get("rssi"),
        "fw": payload.get("fw"),
        "uptime_s": payload.get("uptime_s"),
    }
    st["vitals"][mac] = new_vital
    # Uhrversatz Taster -> Server lernen (Server-Zeit minus Taster-Zeit); Sprung nach unten
    # sofort uebernehmen (geringste Latenz), nach oben nur langsam (Netzwerkjitter).
    clock_ms = payload.get("clock_ms")
    if isinstance(clock_ms, (int, float)) and clock_ms > 1_700_000_000_000:
        offsets = st.setdefault("clock_offsets", {})
        new_off = now_ms() - int(clock_ms)
        old = offsets.get(mac)
        offsets[mac] = new_off if old is None or new_off < old else int(old + (new_off - old) * 0.1)
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
        "mac": str(mac).strip(),
        "name": str(name),
        "ts": int(payload.get("ts", now_ms())),
        "stopwatch_ms": payload.get("stopwatch_ms"),
    }
    # Bekannte MAC: Eintrag aktualisieren statt zu duplizieren
    for existing in st["tasters"]:
        if existing.get("mac") == entry["mac"]:
            existing["name"] = entry["name"]
            existing["ts"] = entry["ts"]
            entry = existing
            break
    else:
        st["tasters"].append(entry)

    # Buchstaben in der Reihenfolge der Anmeldung vergeben (A-J, bleibt dauerhaft erhalten)
    if not entry.get("letter"):
        used = {t.get("letter") for t in st["tasters"]}
        entry["letter"] = next((c for c in TASTER_LETTERS if c not in used), None)

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
        "free": virtual_mem.available,
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
    _maybe_advance_run(st)
    payload = request.get_json(force=True, silent=True) or {}

    mac = payload.get("mac")
    # Testbetrieb: Taster-Druck ohne echten Taster fuer eine Bahn/den Starter ausloesen
    test_lane = payload.get("test_lane")
    if not mac and test_lane is None:
        return jsonify({"ok": False, "error": "missing mac"}), 400

    current_run = st.get("current_run")
    if current_run is None or str(current_run).strip() == "":
        return jsonify({"ok": False, "error": "no current_run selected"}), 400

    ts_val = int(payload.get("ts", now_ms()))

    if test_lane is not None:
        mac_norm = "test"
        lane = str(test_lane)
        ts_val = now_ms()
    else:
        mac_norm = str(mac).strip()
        lane = _lane_for_mac(st, mac_norm)
        # Zeitstempel des Tasters auf die Serveruhr umrechnen. Kleine Versaetze sind nur
        # Netzwerklatenz (je Taster verschieden) und wuerden die Zeiten verfaelschen; korrigiert
        # wird nur bei grober Abweichung (Taster nicht auf Serverzeit synchronisiert).
        offset = int((st.get("clock_offsets") or {}).get(mac_norm, 0))
        if abs(offset) > CLOCK_OFFSET_MIN_MS:
            ts_val += offset

    if lane is None:
        return jsonify({"ok": False, "error": f"no lane found for mac {mac_norm}"}), 400

    # Starter-Druck nach abgeschlossenem Lauf startet sofort den naechsten Lauf
    if lane == STARTER_KEY and st.get("run_finished_ts") is not None:
        _advance_run(st)
        current_run = st["current_run"]

    lanes_in_run = [v["Bahn"] for v in st.get("startcards_per_run", {}).get(str(current_run), [])]
    triggers_per_run = st.get("triggers_per_run", dict)
    triggers_per_run.setdefault(str(current_run), {})
    triggers_per_run[str(current_run)].setdefault(lane, None)
    # Abort press if the run has not been started yet.
    if lane != STARTER_KEY and not any(
        p == STARTER_KEY for p in triggers_per_run[str(current_run)].keys()
    ):
        return jsonify({"ok": False, "error": "Run has not started yet."}), 400
    # Stopp-Sperre: Bahn-Signale kurz nach dem Start werden ignoriert (z. B. Fehlausloesungen)
    if lane != STARTER_KEY:
        starter_press = triggers_per_run[str(current_run)].get(STARTER_KEY)
        lockout_ms = _stop_lockout_ms(st)
        if starter_press and ts_val - int(starter_press["ts"]) < lockout_ms:
            logger.info(f"Stop signal of lane {lane} ignored (lockout {lockout_ms} ms)")
            return jsonify({"ok": True, "ignored": True, "reason": "stop_lockout"})
    # Abort double press
    if triggers_per_run[str(current_run)][lane]:
        return jsonify({"ok": False, "error": "Double press detected."}), 400
    # Reject lanes which are not in the current run, except STARTER
    if lane != STARTER_KEY and lane not in lanes_in_run:
        abort(400, description=f"Lane {lane} is not in the current run.")
    press: PressEvent = {
        "ts": ts_val,
        "mac": mac_norm,
    }

    triggers_per_run[str(current_run)][lane] = press
    st["triggers_per_run"] = triggers_per_run
    save_state(st)
    # Check, if for all lanes presses have been received
    if lanes_in_run and not (set(lanes_in_run) - set(triggers_per_run[str(current_run)].keys())):
        logger.info(f"All lanes have been pressed in run {current_run}")
        _write_heats_xml(st)
        # Nach der eingestellten Wartezeit in den naechsten Lauf wechseln
        st["run_finished_ts"] = now_ms()
    save_state(st)
    return jsonify(
        {
            "ok": True,
            "press": {
                **press,
                "run": current_run,
                "lane": lane,
            },
        }
    )


_UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}


def _ascii(text: Any, limit: int = 30) -> str:
    """Text fuer das Taster-Display: nur ASCII (die Display-Schrift kennt keine Umlaute)."""
    s = "".join(_UMLAUTE.get(ch, ch) for ch in str(text or ""))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return s.replace('"', "").replace("\\", "").strip()[:limit]


def _lane_time(presses: Optional[dict[str, Any]], lane: str) -> Optional[int]:
    """Gestoppte Zeit (ms) einer Bahn in einem Lauf, None wenn nicht gestoppt/nicht gestartet."""
    starter = (presses or {}).get(STARTER_KEY)
    press = (presses or {}).get(lane)
    if not starter or not press:
        return None
    return max(0, int(press["ts"]) - int(starter["ts"]))


@app.get("/api/display")
def api_get_display():
    """
    Anzeigedaten fuer ein Taster-Display (GET /api/display?mac=...).

    role: none | starter | lane. state: ready | running | stopped | inactive.
    elapsed_ms: Laufzeit seit dem Start (nur state running), time_ms: gestoppte Zeit.
    last_*: letzter abgeschlossener Lauf (bei Bahn: letzte Zeit dieser Bahn).
    lanes (nur Starter): Bahnen des Laufs als "bahn,zustand,ms;..." (w/r/s, ms nur bei s).
    """
    st = load_state()
    _maybe_advance_run(st)
    mac = request.args.get("mac", "").strip()
    lane = _lane_for_mac(st, mac) if mac else None
    run = int(st.get("current_run") or 0)
    cards = (st.get("startcards_per_run") or {}).get(str(run), [])
    all_presses = st.get("triggers_per_run") or {}
    presses = all_presses.get(str(run)) or {}
    starter = presses.get(STARTER_KEY)
    now = now_ms()
    finished = st.get("run_finished_ts") is not None

    out: dict[str, Any] = {
        "role": "none",
        "lane": None,
        "run": run,
        "state": "ready",
        "server_now": now,
        "elapsed_ms": None,
        "time_ms": None,
        "name": "",
        "discipline": "",
        "last_ms": None,
        "last_name": "",
        "last_run": None,
    }
    if lane is None:
        return jsonify(out)

    previous_runs = sorted((int(r) for r in all_presses if int(r) < run), reverse=True)

    if lane == STARTER_KEY:
        out["role"] = "starter"
        out["name"] = _ascii(f"{len(cards)} Schwimmer") if cards else ""
        out["discipline"] = _ascii(cards[0].get("Disziplin")) if cards else ""
        # Alle Bahnen des Laufs: "bahn,zustand,ms;..." (w wartet, r laeuft, s gestoppt; ms nur bei s)
        parts = []
        for ln in sorted({str(c.get("Bahn")) for c in cards if str(c.get("Bahn")).isdigit()}, key=int):
            t = _lane_time(presses, ln)
            if t is not None:
                parts.append(f"{ln},s,{t}")
            else:
                parts.append(f"{ln},{'r' if starter else 'w'},-1")
        out["lanes"] = ";".join(parts)
        if starter:
            if finished:
                times = [t for ln in presses if ln != STARTER_KEY
                         if (t := _lane_time(presses, ln)) is not None]
                out["state"] = "stopped"
                out["time_ms"] = max(times) if times else 0
            else:
                out["state"] = "running"
                out["elapsed_ms"] = max(0, now - int(starter["ts"]))
        for r in previous_runs:
            times = [t for ln in all_presses[str(r)] if ln != STARTER_KEY
                     if (t := _lane_time(all_presses[str(r)], ln)) is not None]
            if times:
                out["last_ms"], out["last_run"] = max(times), r
                break
        return jsonify(out)

    out["role"] = "lane"
    out["lane"] = int(lane) if str(lane).isdigit() else None
    card = next((c for c in cards if str(c.get("Bahn")) == str(lane)), None)
    if card is None:
        out["state"] = "inactive"
        out["name"] = "frei"
    else:
        out["name"] = _ascii(card.get("Name"))
        out["discipline"] = _ascii(card.get("Disziplin"))
        stopped = _lane_time(presses, str(lane))
        if stopped is not None:
            out["state"], out["time_ms"] = "stopped", stopped
        elif starter:
            out["state"] = "running"
            out["elapsed_ms"] = max(0, now - int(starter["ts"]))
    for r in previous_runs:
        t = _lane_time(all_presses[str(r)], str(lane))
        if t is not None:
            prev_card = next(
                (c for c in (st.get("startcards_per_run") or {}).get(str(r), [])
                 if str(c.get("Bahn")) == str(lane)), None)
            out["last_ms"], out["last_run"] = t, r
            out["last_name"] = _ascii((prev_card or {}).get("Name"))
            break
    return jsonify(out)


@app.get("/api/run-status")
def api_get_run_status():
    """Aktueller Lauf sowie je Lauf Starter-Zeitstempel und gemessene Zeiten (ms) je Bahn."""
    st = load_state()
    _maybe_advance_run(st)
    runs: dict[str, Any] = {}
    for run, presses in (st.get("triggers_per_run") or {}).items():
        starter = (presses or {}).get(STARTER_KEY)
        starter_ts = starter.get("ts") if starter else None
        times: dict[str, int] = {}
        if isinstance(starter_ts, int):
            for lane, press in presses.items():
                if lane == STARTER_KEY or not press:
                    continue
                times[str(lane)] = press["ts"] - starter_ts
        runs[str(run)] = {"started": starter_ts is not None, "starter_ts": starter_ts, "times_ms": times}
    finished = st.get("run_finished_ts")
    next_in = None
    if finished is not None:
        next_in = max(0, _auto_next_delay_ms(st) - (now_ms() - int(finished))) / 1000
    return jsonify(
        {
            "current_run": st.get("current_run"),
            "server_now": now_ms(),
            "next_run_in_s": next_in,
            "runs": runs,
        }
    )


@app.post("/api/test/reset-run")
def api_test_reset_run():
    """Nur zum Testen: Messung des aktuellen Laufs verwerfen."""
    st = load_state()
    run = str(st.get("current_run"))
    (st.get("triggers_per_run") or {}).pop(run, None)
    st["run_finished_ts"] = None
    save_state(st)
    return jsonify({"ok": True, "run": run})


def _heats_for_xml(st: State) -> list[tuple[int, int, dict[int, int]]]:
    """
    Fertige Laeufe als (Laufnummer, 1, {Bahn: ms}) fuer JAuswertung.

    JAuswertung (Standard-Nummerierung) fuehrt die Laufnummer der Startkarten als <event> und
    den Teillauf (Laufbuchstabe + 1) als <heat>. Nur so waehlt es den Lauf selbst vor.
    Ein Lauf gilt als fertig, wenn alle Bahnen eine Zeit
    haben oder der Lauf schon vor dem aktuellen liegt (Bahnen ohne Zeit fehlen dann).
    """
    cards_per_run = st.get("startcards_per_run") or {}
    current = int(st.get("current_run") or 0)
    event_of: dict[int, int] = {}
    for run, cards in cards_per_run.items():
        try:
            event_of[int(run)] = int(float((cards[0].get("Wettkampf") or 1)))
        except (ValueError, TypeError, IndexError):
            event_of[int(run)] = 1
    heat_of: dict[int, int] = {}
    for event in set(event_of.values()):
        for pos, run in enumerate(sorted(r for r, e in event_of.items() if e == event), start=1):
            heat_of[run] = pos

    heats = []
    for run_s, lane_times in sorted(determine_lane_times_per_run().items()):
        run = int(run_s)
        if run not in event_of or not lane_times:
            continue
        expected = {int(c["Bahn"]) for c in cards_per_run.get(str(run), []) if str(c.get("Bahn")).isdigit()}
        if run >= current and not expected <= set(lane_times):
            continue
        heats.append((run, 1, {int(k): v for k, v in lane_times.items()}))
    return sorted(heats)


def _write_heats_xml(st: State) -> str:
    """Erzeugt das Ergebnis-XML und sichert es zusaetzlich als Datei."""
    xml = create_xml_heats(_heats_for_xml(st))
    try:
        os.makedirs(os.path.dirname(HEATS_XML_PATH), exist_ok=True)
        with open(HEATS_XML_PATH, "w", encoding="utf-8") as f:
            f.write(xml)
        logger.info(f"Wrote results file to {HEATS_XML_PATH}")
    except OSError as exc:
        logger.warning(f"Could not write {HEATS_XML_PATH}: {exc}")
    return xml


@app.route("/legacy/heats.xml")
@app.route("/heats.xml")
def serve_heats_xml():
    # Immer aus dem aktuellen Stand erzeugen, damit JAuswertung nie veraltete Zeiten abholt
    return Response(
        _write_heats_xml(load_state()),
        mimetype="application/xml",
        headers={"Content-Disposition": "attachment; filename=heats.xml"},
    )


@app.get("/tasters")
def tasters_page() -> str:
    return render_template("tasters.html", version=APP_VERSION)


LaneTimesPerRun = dict[str, dict[str, int]]  # run -> lane -> time_ms


def determine_lane_times_per_run() -> LaneTimesPerRun:
    """
    Determine time per lane for each run.

    For each run:
      - reads starter press timestamp (lane key = `starter_key`)
      - for each other lane with at least one PressEvent, uses the first press ts
      - computes delta to starter ts

    Returns:
        lane_times: A dictionary which stores the time for a run and a delta
    """
    lane_times: LaneTimesPerRun = {}
    state = load_state()
    for run, presses_by_run in state["triggers_per_run"].items():
        if not presses_by_run:
            logger.warning(f"No presses recorded for {run=}")
            continue

        starter_presses = presses_by_run.get(STARTER_KEY)
        if not starter_presses:
            logger.warning(f"No starter press recorded for {run=}")
            continue

        if not isinstance(starter_ts := starter_presses.get("ts"), int):
            logger.warning(f"Starter press ts is not an int for {run=}")
            continue

        run_times: dict[str, int] = {}
        # Sort lanes
        presses_by_run = sort_lane_times_by_lane(presses_by_run)
        for lane, lane_presses in presses_by_run.items():
            if lane == STARTER_KEY:
                continue

            if not lane_presses:
                logger.warning(f"No press recorded for {lane=} in {run=}")
                continue

            lane_ts = lane_presses.get("ts")
            if not isinstance(lane_ts, int):
                logger.warning(f"Lane press ts is not an int for {lane=} in {run=}")
                continue

            delta = lane_ts - starter_ts
            if delta < 0:
                logger.warning(
                    f"Lane press ts is before starter press ts for {lane=} in {run=} ({delta=})"
                )
                continue

            run_times[int(lane)] = delta

        lane_times[int(run)] = run_times
    return lane_times


def sort_lane_times_by_lane(presses_by_lane: dict[str, PressEvent]) -> dict[str, PressEvent]:
    """
    Sort lane time of ``presses_by_lane`` ascending.

    Args:
        presses_by_lane: The time per lane.

    Returns:
        the sorted lane time dict.
    """

    def lane_sort_key(lane: str):
        s = str(lane).strip()
        return (0, int(s)) if s.isdigit() else (1, s)

    return dict(sorted(presses_by_lane.items(), key=lambda kv: lane_sort_key(kv[0])))


def main():
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
