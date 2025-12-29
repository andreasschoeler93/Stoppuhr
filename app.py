# ----------------------------------------
# Stoppuhr Webserver
# Version: v0.4.3
# Status: stable-beta
# ----------------------------------------


from __future__ import annotations

import csv
import io
import json
import os
import re
import socket
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Tuple

from flask import Flask, jsonify, render_template, request
from flask.typing import ResponseReturnValue


APP_VERSION = "0.4.3"
DEFAULT_PORT = 8000
EXIT_ERROR = 1

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
STATE_PATH = os.path.join(DATA_DIR, "state.json")

os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static", template_folder="templates")


def _default_state() -> Dict[str, dict[str, Any]]:
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
    }


def load_state() -> Dict[str, dict[str, Any]]:
    if not os.path.exists(STATE_PATH):
        st = _default_state()
        save_state(st)
        return st
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        st = _default_state()
        save_state(st)
        return st


def save_state(state: Dict[str, dict[str, Any]]) -> None:
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


def now_ms() -> int:
    return int(time.time() * 1000)


def run_cmd(cmd: List[str]) -> Tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except Exception as e:
        return EXIT_ERROR, str(e)


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


# --- BEGIN: Taster/Trigger & Data API Ergänzungen ---
def _ensure_keys(st: dict):
    if "runs" not in st:
        st["runs"] = {"current_run": None, "runs": []}
    if "assignments" not in st:
        st["assignments"] = {"mapping": {}, "last_update_ts": None}
    if "vitals" not in st:
        st["vitals"] = []
    if "triggers" not in st:
        st["triggers"] = []


@app.get("/api/runs")
def api_get_runs():
    st = load_state()
    _ensure_keys(st)
    return jsonify(st["runs"])


@app.post("/api/runs")
def api_post_runs():
    st = load_state()
    _ensure_keys(st)
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
    _ensure_keys(st)
    return jsonify(st["assignments"])


@app.post("/api/assignments")
def api_post_assignments():
    st = load_state()
    _ensure_keys(st)
    payload = request.get_json(force=True, silent=True) or {}
    if "mapping" in payload:
        st["assignments"]["mapping"] = payload["mapping"]
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
    return jsonify({"ok": True, "assignments": st["assignments"]})


@app.get("/api/vitals")
def api_get_vitals():
    st = load_state()
    _ensure_keys(st)
    return jsonify(st["vitals"])


@app.post("/api/vitals")
def api_post_vitals():
    st = load_state()
    _ensure_keys(st)
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
    _ensure_keys(st)
    return jsonify(st["triggers"])


@app.post("/api/triggers")
def api_post_triggers():
    st = load_state()
    _ensure_keys(st)
    payload = request.get_json(force=True, silent=True) or {}
    taster = payload.get("taster")
    if not taster:
        return jsonify({"ok": False, "error": "missing taster"}), 400
    entry = {
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

    _, out = run_cmd(["bash", "-lc", "top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'"])
    try:
        cpu_percent = float(out) if out else None
    except Exception:
        cpu_percent = None

    mem = None
    _, out = run_cmd(["bash", "-lc", "free -b | awk '/Mem:/ {print $2,$3,$4}'"])
    try:
        if out:
            total, used, free = [int(x) for x in out.split()]
            mem = {
                "total": total,
                "used": used,
                "free": free,
                "percent": (used / total * 100.0) if total else 0.0,
            }
    except Exception:
        mem = None

    disk = None
    _, out = run_cmd(["bash", "-lc", "df -B1 / | awk 'NR==2 {print $2,$3,$4,$5}'"])
    try:
        if out:
            total, used, free, pct = out.split()
            disk = {
                "total": int(total),
                "used": int(used),
                "free": int(free),
                "percent": float(pct.strip("%")),
            }
    except Exception:
        disk = None

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
    _, gw = run_cmd(["bash", "-lc", "ip route | awk '/default/ {print $3; exit}'"])
    _, dns = run_cmd(
        ["bash", "-lc", "cat /etc/resolv.conf | awk '/^nameserver/ {print $2}' | xargs"]
    )
    dns_servers = dns.split() if dns else []

    interfaces: Dict[str, Any] = {}
    _, out = run_cmd(
        ["bash", "-lc", "ip -o link show | awk -F': ' '{print $2}' | awk '{print $1}'"]
    )
    ifnames = out.split() if out else []
    for ifn in ifnames:
        _, mac = run_cmd(["bash", "-lc", f"cat /sys/class/net/{ifn}/address 2>/dev/null || true"])
        _, state = run_cmd(
            ["bash", "-lc", f"cat /sys/class/net/{ifn}/operstate 2>/dev/null || true"]
        )
        _, ipv4 = run_cmd(
            ["bash", "-lc", f"ip -4 -o addr show {ifn} | awk '{{print $4}}' | head -n1"]
        )
        _, ipv6 = run_cmd(
            ["bash", "-lc", f"ip -6 -o addr show {ifn} | awk '{{print $4}}' | head -n1"]
        )
        interfaces[ifn] = {
            "mac": mac.strip() or None,
            "state": state.strip() or None,
            "ipv4": ipv4.strip() or None,
            "ipv6": ipv6.strip() or None,
        }

    return jsonify(
        {
            "default_gateway": gw.strip() or None,
            "dns_servers": dns_servers,
            "interfaces": interfaces,
        }
    )


def main():
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
