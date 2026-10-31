# ----------------------------------------
# Stoppuhr Webserver
# Version: v0.21.1
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
import threading
import time
import unicodedata
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Final, Optional, TypedDict

import psutil
import redis
from flask import Flask, Response, abort, g, jsonify, redirect, render_template, request, send_file, session
from flask.sessions import SecureCookieSessionInterface
from flask.typing import ResponseReturnValue
import archive
import auth
import firmware_store
import charger_firmware
import ladekoffer
import limits as limits_module
import node_info
import pi_update
import vitals_history
import finish as finish_module
import wifi_config
from xml_writer import create_xml_heats


APP_VERSION: Final[str] = "0.21.1"
DEFAULT_PORT: Final[int] = 1999  # Since JAuswertung expected this port
EXIT_ERROR: Final[int] = 1
STATE_KEY: Final[str] = "STATE"
STARTER_KEY: Final[str] = "starter"
FINISH_KEY: Final[str] = finish_module.FINISH_KEY
STARTER_STOP_MIN_MS: Final[int] = 1500  # Zweiter Starter-Druck davor gilt als Prellen
STARTER_FINISH_GRACE_MS: Final[int] = 5000  # Kombirolle: so lange nach Lauf-Ende zaehlt ein Druck noch als Zieleinlauf
CLOCK_OFFSET_MIN_MS: Final[int] = 250
KEEP_HOURS_DEFAULT: Final[float] = 6.0
HEATS_XML_PATH: Final[str] = os.environ.get("HEATS_XML_PATH", "/app/results/heats.xml")


app = Flask(__name__, static_folder="static", template_folder="templates")
app.json.ensure_ascii = False
redis_store = redis.Redis(
    host=os.environ.get("REDIS_HOST", "redis"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    db=0,
    decode_responses=True,
)
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
    ssid: Optional[str]
    wv: Optional[int]


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
    shutdown_until_ms: int
    start_locked_until_ms: int
    startcards: dict[str, Any]
    tasters: list[Taster]
    vitals: dict[str, Vital]
    current_run: int
    current_attempt: int
    aborted_attempts: list[str]
    abort_requests: dict[str, Any]
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
            "shutdown_grace_s": "10",
            "starter_is_finish": "0",
            "low_battery_pct": "10",
            "low_battery_min": "5",
        },
        "shutdown_until_ms": 0,
        "start_locked_until_ms": 0,
        "startcards": {
            "loaded": False,
            "last_fetch_ts": None,
            "row_count": 0,
            "rows": [],
            "last_error": None,
            "source_url": None,
            "max_lane": 0,
            "runs": [],
        },
        "tasters": [],  # Taster melden sich selbst per POST /api/taster an
        "results": {},
        "assignments": {"mapping": {}, "pending": {}, "last_update_ts": None},
        "vitals": {},  # Maps the mac address to the vitals
        "startcards_per_run": defaultdict(list),
        "triggers_per_run": {},
        "current_run": 1,
        "current_attempt": 1,
        "aborted_attempts": [],
        "abort_requests": {},
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


def _is_range_test_taster(st: State, mac: str) -> bool:
    """True, wenn der Funktest laeuft und dieser Taster der gewaehlte Buchstabe ist."""
    settings = st.get("settings", {})
    letter = str(settings.get("range_test_letter") or "").strip().upper()
    if not letter or str(settings.get("range_test_on", "0")) != "1":
        return False
    return any(t.get("mac") == mac and str(t.get("letter") or "").upper() == letter for t in st.get("tasters", []))


DEFAULT_WAKE_PINS: Final[str] = "8,9,10,11,12,13,14,15,0,1"


def _parse_wake_pins(value: Any) -> Optional[list[int]]:
    """MCP-Pins (0..15) der Magnet-Trigger fuer Slot 1..10; None bei ungueltiger Eingabe."""
    try:
        pins = [int(p) for p in str(value).replace(";", ",").replace(" ", ",").split(",") if p.strip()]
    except ValueError:
        return None
    if len(pins) != 10 or any(not 0 <= p <= 15 for p in pins):
        return None
    return pins


def _wake_config(st: State) -> dict[str, Any]:
    """Wecksequenz des Ladekoffers; wird dem Koffer in der Antwort auf POST /api/charger mitgegeben."""
    pins = _parse_wake_pins(st.get("settings", {}).get("charger_wake_pins", DEFAULT_WAKE_PINS))
    return {
        "pins": pins or _parse_wake_pins(DEFAULT_WAKE_PINS),
        "ms": _int_setting(st, "charger_wake_ms", 3000),
        "gap_ms": _int_setting(st, "charger_wake_gap_ms", 1000),
    }


def _int_setting(st: State, key: str, default: int) -> int:
    try:
        return int(st.get("settings", {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _stop_lockout_ms(st: State) -> int:
    """Stopp-Sperre nach dem Start in ms (Einstellung, Standard 5 s, 0 = aus)."""
    try:
        return max(0, int(st.get("settings", {}).get("stop_lockout_s", 5))) * 1000
    except (TypeError, ValueError):
        return 5_000


def _advance_run(st: State) -> None:
    st["current_run"] = int(st.get("current_run") or 0) + 1
    st["current_attempt"] = 1
    st["run_finished_ts"] = None
    save_state(st)


def _maybe_advance_run(st: State) -> None:
    """Springt in den naechsten Lauf, wenn der abgeschlossene Lauf lange genug angezeigt wurde."""
    finished = st.get("run_finished_ts")
    if finished is not None and now_ms() - int(finished) >= _auto_next_delay_ms(st):
        # Lesende Routen laufen ohne Sperre; nur das Weiterschalten sperrt und liest neu
        with _STATE_LOCK:
            fresh = load_state()
            if fresh.get("run_finished_ts") is not None:
                _advance_run(fresh)
            st.clear()
            st.update(fresh)


def _parse_attempt_key(key: str) -> Optional[tuple[int, int]]:
    try:
        run_s, separator, attempt_s = str(key).partition("/")
        run = int(run_s)
        attempt = int(attempt_s) if separator else 1
    except ValueError:
        return None
    if run < 1 or attempt < 1:
        return None
    return run, attempt


def _attempt_key(run: int, attempt: int) -> str:
    return str(run) if attempt == 1 else f"{run}/{attempt}"


def _adopted_versions(st: State, run_key: str) -> list[dict[str, Any]]:
    """Uebertragene Zieleinlauf-Versionen eines Versuchs (alter Stand v0.13.2: einzelnes Dict)."""
    value = (st.get("finish_adopted") or {}).get(run_key)
    if isinstance(value, dict):
        return [value]
    return list(value or [])


def _next_attempt(st: State, run: int) -> int:
    attempts = [
        attempt
        for key in (st.get("triggers_per_run") or {})
        if (parsed := _parse_attempt_key(key)) is not None
        for existing_run, attempt in [parsed]
        if existing_run == run
    ]
    # Unterversionen aus uebernommenen Zieleinlauf-Zeiten sind ebenfalls vergeben
    for key in (st.get("finish_adopted") or {}):
        parsed = _parse_attempt_key(key)
        if parsed is not None and parsed[0] == run:
            attempts.extend(int(entry["attempt"]) for entry in _adopted_versions(st, key))
    return max(attempts, default=0) + 1


def _prepare_attempt(st: State, run: int) -> int:
    old_run = int(st.get("current_run") or 0)
    old_attempt = int(st.get("current_attempt") or 1)
    old_key = _attempt_key(old_run, old_attempt) if old_run else ""
    old_presses = (st.get("triggers_per_run") or {}).get(old_key) or {}
    if st.get("run_finished_ts") is None and old_presses.get(STARTER_KEY):
        aborted = set(st.get("aborted_attempts") or [])
        aborted.add(old_key)
        st["aborted_attempts"] = sorted(aborted)

    current_key = _attempt_key(run, old_attempt)
    existing_attempt = (st.get("triggers_per_run") or {}).get(current_key)
    if old_run == run and not existing_attempt:
        attempt = old_attempt
    else:
        attempt = _next_attempt(st, run)
    st["current_run"] = run
    st["current_attempt"] = attempt
    st["run_finished_ts"] = None
    st["start_locked_until_ms"] = now_ms() + _stop_lockout_ms(st)
    return attempt


# ----------------------------------------
# Anmeldung (Weboberflaeche). Die Schnittstellen der Taster und der Export fuer JAuswertung
# bleiben offen, sonst koennten sich die Taster nicht mehr melden.
# ----------------------------------------
_OPEN_ROUTES: Final[frozenset[tuple[str, str]]] = frozenset({
    ("GET", "/login"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/setup"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/version"),
    ("POST", "/api/taster"),
    ("POST", "/api/vitals"),
    ("POST", "/api/charger"),
    ("GET", "/api/charger/firmware"),
    ("POST", "/api/triggers"),
    ("GET", "/api/display"),
    ("POST", "/api/abort-run"),
    ("GET", "/api/firmware/download"),
    ("POST", "/api/ota-status"),
    ("GET", "/heats.xml"),
    ("GET", "/legacy/heats.xml"),
})
LOGIN_MAX_FAILS: Final[int] = 5
LOGIN_WINDOW_S: Final[int] = 60
_login_fails: dict[str, list[float]] = defaultdict(list)


def _auth_active() -> bool:
    return not app.config.get("AUTH_DISABLED")


@app.before_request
def _require_login() -> Optional[ResponseReturnValue]:
    if not _auth_active():
        return None
    method = "GET" if request.method == "HEAD" else request.method
    path = request.path
    if path.startswith("/static/"):
        return None
    is_open = (method, path) in _OPEN_ROUTES
    if is_open:
        return None
    try:
        cred = auth.load(redis_store)
    except redis.RedisError:
        return jsonify({"ok": False, "error": "Redis nicht erreichbar"}), 503
    if cred and session.get("u") == cred["user"] and session.get("f") == auth.fingerprint(cred):
        return None
    if path.startswith("/api/"):
        return jsonify({"ok": False, "error": "auth", "setup": cred is None}), 401
    return redirect("/login")


# Der Zustand wird als Ganzes geladen, geaendert und gespeichert. Ohne Sperre ueberschreiben sich
# gleichzeitige Anfragen (z. B. zwei Taster, die zugleich druecken) gegenseitig und ein Druck geht verloren.
# Deshalb laufen alle API-Anfragen nacheinander; nur langsame Routen ohne Zustandsaenderung sind ausgenommen.
_STATE_LOCK: Final = threading.RLock()
_STATE_LOCK_TIMEOUT_S: Final[int] = 10
_UNLOCKED_PREFIXES: Final[tuple[str, ...]] = (
    "/api/startcards/reload", "/api/pi-update", "/api/cluster", "/api/system-status", "/api/wifi-config",
    "/api/firmware/releases", "/api/firmware/deploy", "/api/firmware/download",
    "/api/charger/firmware", "/api/charger-firmware", "/api/vitals/pi", "/api/vitals/history",
    "/api/archive",
)


@app.before_request
def _state_lock_enter() -> None:
    path = request.path
    # Reine Lese-Abfragen (Browser, Taster-Displays) blockieren nicht; sie schreiben den Zustand nicht
    if request.method in ("GET", "HEAD") and path != "/api/network-status":
        return
    if path.startswith("/api/") and not path.startswith(_UNLOCKED_PREFIXES):
        g.state_locked = _STATE_LOCK.acquire(timeout=_STATE_LOCK_TIMEOUT_S)


@app.teardown_request
def _state_lock_exit(_exc: Optional[BaseException]) -> None:
    if g.pop("state_locked", False):
        _STATE_LOCK.release()


class _RedisKeySessions(SecureCookieSessionInterface):
    """Sitzungs-Cookies mit dem Schluessel aus Redis (beide Pis teilen ihn)."""

    def get_signing_serializer(self, app: Flask):
        if not app.secret_key:
            try:
                app.secret_key = auth.secret(redis_store)
            except redis.RedisError:
                return None
        return super().get_signing_serializer(app)


app.session_interface = _RedisKeySessions()


def _login_session(cred: dict[str, str]) -> None:
    session.clear()
    session.permanent = True
    session["u"] = cred["user"]
    session["f"] = auth.fingerprint(cred)


app.permanent_session_lifetime = 30 * 24 * 3600
app.config.update(SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True)


@app.get("/login")
def login_page() -> str:
    try:
        setup = auth.load(redis_store) is None
    except redis.RedisError:
        setup = False
    return render_template("login.html", version=APP_VERSION, setup=setup)


@app.post("/api/auth/login")
def api_auth_login() -> ResponseReturnValue:
    body = request.get_json(silent=True) or {}
    ip = request.remote_addr or "?"
    recent = [t for t in _login_fails[ip] if time.time() - t < LOGIN_WINDOW_S]
    _login_fails[ip] = recent
    if len(recent) >= LOGIN_MAX_FAILS:
        return jsonify({"ok": False, "error": "Zu viele Versuche, bitte eine Minute warten"}), 429
    user, password = str(body.get("user", "")), str(body.get("password", ""))
    if not auth.verify(redis_store, user, password):
        _login_fails[ip].append(time.time())
        return jsonify({"ok": False, "error": "Benutzer oder Kennwort falsch"}), 401
    _login_fails.pop(ip, None)
    _login_session(auth.load(redis_store))
    return jsonify({"ok": True})


@app.post("/api/auth/setup")
def api_auth_setup() -> ResponseReturnValue:
    """Erster Zugang: nur moeglich, solange noch keiner festgelegt ist."""
    body = request.get_json(silent=True) or {}
    user, password = str(body.get("user", "")), str(body.get("password", ""))
    problem = auth.validate(user, password)
    if problem:
        return jsonify({"ok": False, "error": problem}), 400
    try:
        created = auth.create_first(redis_store, user, password)
    except redis.ReadOnlyError:
        return jsonify({"ok": False, "error": "Dieser Pi ist gerade nur Kopie (Redis schreibgeschÃ¼tzt)"}), 503
    if not created:
        return jsonify({"ok": False, "error": "Es gibt bereits einen Zugang"}), 409
    _login_session(auth.load(redis_store))
    return jsonify({"ok": True})


@app.post("/api/auth/logout")
def api_auth_logout() -> ResponseReturnValue:
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/auth/status")
def api_auth_status() -> ResponseReturnValue:
    return jsonify({"ok": True, "user": session.get("u")})


@app.post("/api/auth/change")
def api_auth_change() -> ResponseReturnValue:
    body = request.get_json(silent=True) or {}
    cred = auth.load(redis_store) or {}
    if not auth.verify(redis_store, str(cred.get("user", "")), str(body.get("current", ""))):
        return jsonify({"ok": False, "error": "Aktuelles Kennwort falsch"}), 403
    user, password = str(body.get("user", "")), str(body.get("password", ""))
    problem = auth.validate(user, password)
    if problem:
        return jsonify({"ok": False, "error": problem}), 400
    auth.replace(redis_store, user, password)
    _login_session(auth.load(redis_store))
    return jsonify({"ok": True})

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
    if "starter_is_finish" in payload:
        settings["starter_is_finish"] = "1" if payload["starter_is_finish"] in (True, 1, "1", "true") else "0"
    for key, upper in (("low_battery_pct", 100), ("low_battery_min", 1440)):
        if key in payload:
            try:
                value = int(payload[key])
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": f"{key} must be a number"}), 400
            if not 0 <= value <= upper:
                return jsonify({"ok": False, "error": f"{key} must be between 0 and {upper}"}), 400
            settings[key] = str(value)
    if "range_test_letter" in payload:
        letter = str(payload["range_test_letter"] or "").strip().upper()
        if letter and (len(letter) != 1 or letter not in TASTER_LETTERS):
            return jsonify({"ok": False, "error": "Ungültiger Tasterbuchstabe."}), 400
        settings["range_test_letter"] = letter
    if "range_test_on" in payload:
        settings["range_test_on"] = "1" if payload["range_test_on"] in (True, 1, "1", "true") else "0"
        if settings["range_test_on"] == "1" and not settings.get("range_test_letter"):
            return jsonify({"ok": False, "error": "Bitte zuerst einen Tasterbuchstaben eingeben."}), 400
    for key in ("alert_beep_yellow", "alert_beep_red"):
        if key in payload:
            settings[key] = "1" if payload[key] in (True, 1, "1", "true") else "0"
    for key, lower, upper in (
        ("alert_red_len_s", 1, 30),
        ("alert_red_every_s", 1, 3600),
        ("charger_wake_ms", 500, 30_000),
        ("charger_wake_gap_ms", 100, 30_000),
    ):
        if key in payload:
            try:
                value = int(payload[key])
            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": f"{key} must be a number"}), 400
            if not lower <= value <= upper:
                return jsonify({"ok": False, "error": f"{key} must be between {lower} and {upper}"}), 400
            settings[key] = str(value)
    if "charger_wake_pins" in payload:
        pins = _parse_wake_pins(payload["charger_wake_pins"])
        if pins is None:
            return jsonify({"ok": False, "error": "charger_wake_pins: 10 Zahlen von 0 bis 15, durch Komma getrennt"}), 400
        settings["charger_wake_pins"] = ",".join(str(p) for p in pins)
    if "shutdown_grace_s" in payload:
        try:
            shutdown_grace_s = int(payload["shutdown_grace_s"])
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "shutdown_grace_s must be a number"}), 400
        if not 1 <= shutdown_grace_s <= 86_400:
            return jsonify(
                {"ok": False, "error": "shutdown_grace_s must be between 1 and 86400"}
            ), 400
        settings["shutdown_grace_s"] = str(shutdown_grace_s)
    st["settings"] = settings
    save_state(st)
    return jsonify({"ok": True, "settings": settings})


@app.get("/api/limits")
def api_get_limits() -> ResponseReturnValue:
    st = load_state()
    return jsonify({"limits": limits_module.merged(st.get("settings", {}).get("limits")),
                    "defaults": limits_module.defaults()})


@app.post("/api/limits")
def api_set_limits() -> ResponseReturnValue:
    payload = request.get_json(force=True, silent=True) or {}
    if payload.get("reset") is True:
        new_limits: Any = limits_module.defaults()
    else:
        new_limits, error = limits_module.validate(payload.get("limits"))
        if error:
            return jsonify({"ok": False, "error": error}), 400
    st = load_state()
    settings = st.get("settings", {})
    settings["limits"] = new_limits
    st["settings"] = settings
    save_state(st)
    return jsonify({"ok": True, "limits": new_limits})


@app.post("/api/competition/end")
def api_end_competition() -> ResponseReturnValue:
    st = load_state()
    try:
        shutdown_grace_s = int(st.get("settings", {}).get("shutdown_grace_s", "10"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid shutdown_grace_s setting"}), 500
    if not 1 <= shutdown_grace_s <= 86_400:
        return jsonify({"ok": False, "error": "invalid shutdown_grace_s setting"}), 500

    payload = request.get_json(force=True, silent=True) or {}
    name = str(payload.get("name") or "").strip()[:80]
    archive_id = None
    if name:
        # Erst sichern, dann loeschen: schlaegt das Speichern fehl, bleibt der Wettkampf unveraendert
        try:
            archive_id = _archive_competition(st, name)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Archivieren fehlgeschlagen")
            return jsonify({"ok": False, "error": f"Archivieren fehlgeschlagen: {exc}"}), 500
    st["competition_since_ms"] = now_ms()
    # Der Vitalverlauf bleibt erhalten; die Buchstaben merken, damit er beschriftet bleibt
    for t in st.get("tasters", []):
        vitals_history.set_label(redis_store, str(t.get("mac")), t.get("letter"))

    st["shutdown_until_ms"] = now_ms() + shutdown_grace_s * 1000
    st["startcards"] = {
        "loaded": False,
        "last_fetch_ts": None,
        "row_count": 0,
        "rows": [],
        "last_error": None,
        "source_url": None,
        "max_lane": 0,
        "runs": [],
    }
    st["tasters"] = []
    st["vitals"] = {}
    st["results"] = {}
    st["assignments"] = {"mapping": {}, "pending": {}, "last_update_ts": None}
    st["startcards_per_run"] = {}
    st["triggers_per_run"] = {}
    st["finish_per_run"] = {}
    st["finish_assign"] = {}
    st["finish_parked"] = {}
    st["finish_adopted"] = {}
    st["stopped_by_starter"] = []
    st["clock_offsets"] = {}
    st["current_run"] = 1
    st["current_attempt"] = 1
    st["start_locked_until_ms"] = 0
    st["aborted_attempts"] = []
    st["abort_requests"] = {}
    st["run_finished_ts"] = None
    save_state(st)
    _write_heats_xml(st)
    return jsonify(
        {
            "ok": True,
            "archive_id": archive_id,
            "shutdown_until_ms": st["shutdown_until_ms"],
            "shutdown_grace_s": shutdown_grace_s,
        }
    )


def _archive_competition(st: State, name: str) -> str:
    """Sichert Ergebnisse, Rohdaten und Vitalverlauf des laufenden Wettkampfs im Archiv."""
    ended = now_ms()
    since = int(st.get("competition_since_ms") or 0)
    heats = _heats_for_xml(st)
    tasters = [{"mac": t.get("mac"), "letter": t.get("letter"), "name": t.get("name")} for t in st.get("tasters", [])]
    competition: dict[str, Any] = {
        "id": str(ended),
        "name": name,
        "since_ts": since,
        "ended_ts": ended,
        "app_version": APP_VERSION,
        "heats": [[run, attempt, {str(lane): ms for lane, ms in times.items()}] for run, attempt, times in heats],
        "xml": create_xml_heats(heats),
        "startcards_per_run": st.get("startcards_per_run") or {},
        "tasters": tasters,
        "vitals": {
            str(t["mac"]): vitals_history.history(redis_store, str(t["mac"]), since) for t in tasters if t["mac"]
        },
        "pi": {n: vitals_history.history_pi(redis_store, n, since) for n in ("Koffer-Pi", "Bad-Pi", "Pi")},
        "starts": vitals_history.starts(redis_store, since),
        "raw": {
            key: st.get(key)
            for key in (
                "triggers_per_run", "finish_per_run", "finish_assign", "finish_parked", "finish_adopted",
                "stopped_by_starter", "aborted_attempts", "assignments",
            )
        },
    }
    competition["pi"] = {n: pts for n, pts in competition["pi"].items() if pts}
    archive.save(redis_store, competition)
    return competition["id"]


@app.get("/api/archive")
def api_archive_list() -> ResponseReturnValue:
    return jsonify({"items": archive.list_all(redis_store)})


@app.get("/api/archive/<cid>")
def api_archive_get(cid: str) -> ResponseReturnValue:
    data = archive.load(redis_store, cid)
    if data is None:
        return jsonify({"ok": False, "error": "Wettkampf nicht gefunden."}), 404
    data.pop("raw", None)  # Rohdaten bleiben im Archiv, die Oberflaeche braucht sie nicht
    return jsonify(data)


@app.get("/api/archive/<cid>/heats.xml")
def api_archive_xml(cid: str) -> ResponseReturnValue:
    data = archive.load(redis_store, cid)
    if data is None:
        return jsonify({"ok": False, "error": "Wettkampf nicht gefunden."}), 404
    return Response(
        data.get("xml") or "",
        mimetype="application/xml",
        headers={"Content-Disposition": f'attachment; filename="heats-{cid}.xml"'},
    )


@app.get("/api/archive/<cid>/raw.json")
def api_archive_raw(cid: str) -> ResponseReturnValue:
    data = archive.load(redis_store, cid)
    if data is None:
        return jsonify({"ok": False, "error": "Wettkampf nicht gefunden."}), 404
    return Response(
        json.dumps(data, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="wettkampf-{cid}.json"'},
    )


@app.delete("/api/archive/<cid>")
def api_archive_delete(cid: str) -> ResponseReturnValue:
    if not archive.delete(redis_store, cid):
        return jsonify({"ok": False, "error": "Wettkampf nicht gefunden."}), 404
    return jsonify({"ok": True})


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
        "ssid": v.get("ssid"),
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
    finish_taster = mac_to_taster.get(current_mapping.get(FINISH_KEY))

    # Get the set of MAC addresses that are already assigned to a lane
    mapped_macs = set(current_mapping.values())
    pending_map = st.get("assignments", {}).get("pending", {}) or {}
    pending_by_mac = {mac: lane_key for lane_key, mac in pending_map.items()}
    # Filter tasters whose MAC is not in the mapped_macs set
    unmapped_tasters = [
        {**t, "pending_lane": pending_by_mac.get(t.get("mac"))}
        for t in tasters
        if t.get("mac") not in mapped_macs
    ]

    return jsonify(
        {
            "mapping": full_mapping,
            "starter": starter_taster,
            "finish": finish_taster,
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
    had_pending = st["assignments"].setdefault("pending", {}).pop(lane_key, None) is not None

    if lane_key in current_mapping:
        del current_mapping[lane_key]
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
        return jsonify({"ok": True, "mapping": current_mapping})

    if had_pending:
        save_state(st)
    return jsonify({"ok": True, "message": "lane was not assigned"})


@app.post("/api/cancel-pending")
def api_cancel_pending():
    """Verwirft einen vorgemerkten Tausch (Bereitschaft) fuer eine Bahn bzw. den Starter."""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    lane = payload.get("lane")
    if not lane:
        return jsonify({"ok": False, "error": "missing lane"}), 400
    pending = st["assignments"].setdefault("pending", {})
    removed = pending.pop(str(lane), None) is not None
    if removed:
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
    return jsonify({"ok": True, "removed": removed})


def _run_in_progress(st: State) -> bool:
    """True, wenn der aktuelle Versuch gestartet und noch nicht abgeschlossen ist."""
    run = st.get("current_run")
    if run is None or str(run).strip() == "":
        return False
    key = _attempt_key(int(run), int(st.get("current_attempt") or 1))
    presses = (st.get("triggers_per_run") or {}).get(key) or {}
    return bool(presses.get(STARTER_KEY)) and st.get("run_finished_ts") is None


def _try_pending_swap(st: State, mac: str) -> Optional[str]:
    """
    Fuehrt einen vorgemerkten Taster-Tausch aus, wenn dieser Taster zum ersten Mal gedrueckt wird.

    Returns:
        Lane-Schluessel nach erfolgtem Tausch, "waiting" (Lauf laeuft noch) oder None (kein Tausch vorgemerkt).
    """
    pending = (st.get("assignments") or {}).get("pending") or {}
    lane_key = next((k for k, v in pending.items() if v == mac), None)
    if lane_key is None:
        return None
    if _run_in_progress(st):
        return "waiting"
    mapping = st["assignments"]["mapping"]
    for key, mapped in list(mapping.items()):
        if mapped == mac:
            del mapping[key]
    mapping[lane_key] = mac
    del pending[lane_key]
    st["assignments"]["last_update_ts"] = now_ms()
    return lane_key


@app.post("/api/assign")
def api_post_assign():
    """
    Assigns a MAC address to a specific lane.

    Ist die Bahn schon mit einem anderen Taster belegt und der neue Taster noch ohne Rolle,
    wird der Tausch nur vorgemerkt (Bereitschaft). Er greift beim ersten Druck des neuen
    Tasters, wenn kein Lauf laeuft. Mit "immediate": true wird sofort getauscht.
    """
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    mac = payload.get("mac")
    lane = payload.get("lane")

    if not mac or not lane:
        return jsonify({"ok": False, "error": "missing mac or lane"}), 400

    lane_key = str(lane)
    current_mapping = st["assignments"]["mapping"]
    pending = st["assignments"].setdefault("pending", {})

    occupant = current_mapping.get(lane_key)
    if (
        occupant
        and occupant != mac
        and mac not in current_mapping.values()
        and not payload.get("immediate")
    ):
        for key, value in list(pending.items()):
            if value == mac:
                del pending[key]
        pending[lane_key] = mac
        st["assignments"]["last_update_ts"] = now_ms()
        save_state(st)
        return jsonify({"ok": True, "pending": True, "mapping": current_mapping, "pending_map": pending})

    # Remove this MAC from any other lanes it might be assigned to
    for key, value in list(current_mapping.items()):
        if value == mac:
            del current_mapping[key]
    for key, value in list(pending.items()):
        if value == mac or key == lane_key:
            del pending[key]

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
        "ssid": payload.get("ssid"),
        "wv": payload.get("wv") if isinstance(payload.get("wv"), int) else None,
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
    vitals_history.add(redis_store, str(mac), new_vital["ts"], dict(new_vital))
    known_taster = next((t for t in st["tasters"] if t.get("mac") == mac), None)
    if known_taster:
        vitals_history.set_label(redis_store, str(mac), known_taster.get("letter"))
    return jsonify({"ok": True, "vital": new_vital})


@app.post("/api/charger")
def api_post_charger():
    """Statusmeldung der Ladeplatine des Ladekoffers (ohne Anmeldung, wie die Taster)."""
    status = ladekoffer.sanitize(request.get_json(force=True, silent=True))
    if status is None:
        return jsonify({"ok": False, "error": "invalid payload"}), 400
    # Der Server-Zeitstempel zaehlt, die Platine hat keine Uhr
    status["ts"] = now_ms()
    ladekoffer.save(redis_store, status)
    st = load_state()
    reply: dict[str, Any] = {"ok": True, "wake": _wake_config(st), "beep": _beep_config(st)}
    ota = charger_firmware.offer(redis_store, str(status.get("fw") or ""))
    if ota:
        reply["ota"] = ota
    return jsonify(reply)


@app.get("/api/charger/firmware")
def api_charger_firmware_download():
    """Firmware-Datei fuer den Ladekoffer (ohne Anmeldung, nur wenn ein Update bereitliegt)."""
    if charger_firmware.meta(redis_store) is None:
        abort(404)
    return send_file(charger_firmware.FILE, mimetype="application/octet-stream", conditional=False)


@app.get("/api/charger-firmware")
def api_charger_firmware_info():
    status = ladekoffer.load(redis_store)
    error = None
    releases: list[dict[str, Any]] = []
    try:
        releases = [{k: v for k, v in r.items() if k != "url"} for r in charger_firmware.list_releases()]
    except Exception as exc:  # Netzwerk, JSON, Rate-Limit
        error = f"GitHub nicht erreichbar: {exc}"
    return jsonify({
        "uploaded": charger_firmware.meta(redis_store),
        "running": status.get("fw") if status else None,
        "releases": releases,
        "error": error,
    })


@app.post("/api/charger-firmware/deploy")
def api_charger_firmware_deploy():
    """Gewaehlte Version von GitHub laden und dem Koffer anbieten."""
    tag = str((request.get_json(silent=True) or {}).get("tag", ""))
    if firmware_store.parse_tag(tag) is None:
        return jsonify({"ok": False, "error": "Ungueltige Version"}), 400
    try:
        meta = charger_firmware.download_release(redis_store, tag)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Download fehlgeschlagen: {exc}"}), 502
    logger.info("Koffer-Firmware %s von GitHub geladen", tag)
    return jsonify({"ok": True, "uploaded": meta})


@app.post("/api/charger-firmware")
def api_charger_firmware_upload():
    file = request.files.get("file")
    if file is None:
        return jsonify({"ok": False, "error": "Keine Datei gewaehlt."}), 400
    data = file.read(charger_firmware.MAX_SIZE + 1)
    try:
        meta = charger_firmware.save(redis_store, data)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    logger.info("Koffer-Firmware %s hochgeladen", meta["version"])
    return jsonify({"ok": True, "uploaded": meta})


@app.delete("/api/charger-firmware")
def api_charger_firmware_delete():
    charger_firmware.clear(redis_store)
    return jsonify({"ok": True})


ALERT_STATE_KEY: Final[str] = "ALERT_STATE"
ALERT_STALE_MS: Final[int] = 30_000


def _alert_state() -> dict[str, Any]:
    raw = redis_store.get(ALERT_STATE_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _beep_config(st: State) -> dict[str, Any]:
    """Ton fuer den Pieper des Ladekoffers: gelb = kurzer Piepton bei neuer Meldung, rot = langer Ton im Intervall."""
    state = _alert_state()
    # Meldet kein Dashboard mehr (Laptop zu), gibt es auch keine Meldungen
    fresh = now_ms() - int(state.get("ts") or 0) <= ALERT_STALE_MS
    settings = st.get("settings", {})
    return {
        "yellow_on": 1 if fresh and settings.get("alert_beep_yellow", "1") == "1" else 0,
        "yellow_seq": int(state.get("yellow_seq") or 0),
        "red_on": 1 if fresh and state.get("red") and settings.get("alert_beep_red", "1") == "1" else 0,
        "red_ms": _int_setting(st, "alert_red_len_s", 2) * 1000,
        "red_every_ms": _int_setting(st, "alert_red_every_s", 10) * 1000,
    }


@app.post("/api/alert-state")
def api_post_alert_state() -> ResponseReturnValue:
    """Das Dashboard meldet seine aktuellen gelben/roten Meldungen; der Ladekoffer holt sich daraus den Ton."""
    payload = request.get_json(force=True, silent=True) or {}

    def texts(key: str) -> list[str]:
        items = payload.get(key)
        return sorted({str(t)[:200] for t in items})[:50] if isinstance(items, list) else []

    yellow, red = texts("yellow"), texts("red")
    prev = _alert_state()
    seq = int(prev.get("yellow_seq") or 0)
    if any(t not in (prev.get("yellow") or []) for t in yellow):
        seq += 1
    redis_store.set(
        ALERT_STATE_KEY, json.dumps({"ts": now_ms(), "yellow": yellow, "red": bool(red), "yellow_seq": seq})
    )
    return jsonify({"ok": True})


@app.get("/api/charger")
def api_get_charger():
    """Zustand des Ladekoffers mit Statusmeldungen; known=false, solange nie etwas gemeldet wurde."""
    return jsonify(ladekoffer.evaluate(ladekoffer.load(redis_store), now_ms()))


VITALS_MAX_POINTS: Final[int] = 1500


def _thin(points: list[Any]) -> list[Any]:
    """Dünnt lange Verläufe aus (jeder n-te Punkt), damit die Anzeige bei 48 h schnell bleibt."""
    step = -(-len(points) // VITALS_MAX_POINTS)
    return points if step <= 1 else points[::step] + ([points[-1]] if (len(points) - 1) % step else [])


@app.get("/api/vitals/known")
def api_vitals_known():
    """Taster mit Verlauf (auch nach Wettkampfende, wenn sie nicht mehr angemeldet sind)."""
    hours = min(max(request.args.get("hours", default=KEEP_HOURS_DEFAULT, type=float), 0.1), vitals_history.KEEP_HOURS)
    return jsonify({"tasters": vitals_history.known(redis_store, now_ms() - int(hours * 3600 * 1000))})


@app.get("/api/vitals/history")
def api_vitals_history():
    """Messpunkte [ts, Akku %, Akku V, Temperatur, Feuchte, RSSI] der letzten Stunden."""
    mac = request.args.get("mac", "")
    hours = min(max(request.args.get("hours", default=KEEP_HOURS_DEFAULT, type=float), 0.1), vitals_history.KEEP_HOURS)
    since = now_ms() - int(hours * 3600 * 1000)
    return jsonify({"mac": mac, "fields": list(vitals_history.FIELDS),
                    "points": _thin(vitals_history.history(redis_store, mac, since)),
                    "starts": vitals_history.starts(redis_store, since)})


@app.get("/api/vitals/pi")
def api_vitals_pi():
    """Aktueller Zustand und Verlauf der Pis: [ts, CPU-Temperatur, CPU-Last %, Speicher %]."""
    hours = min(max(request.args.get("hours", default=KEEP_HOURS_DEFAULT, type=float), 0.1), vitals_history.KEEP_HOURS)
    since = now_ms() - int(hours * 3600 * 1000)
    data = node_info.cluster_status()
    nodes = []
    for n in [data["self"]] + ([data["peer"]] if data["peer"].get("configured") else []):
        name = _pi_name(n)
        nodes.append({
            "name": name, "reachable": bool(n.get("reachable")), "active": bool(n.get("has_vip")),
            "cpu_temp": n.get("cpu_temp"), "cpu_percent": n.get("cpu_percent"),
            "mem_percent": n.get("mem_percent"), "disk_percent": n.get("disk_percent"),
            "uptime_s": n.get("uptime_s"),
            "points": _thin(vitals_history.history_pi(redis_store, name, since)),
        })
    return jsonify({"fields": list(vitals_history.PI_FIELDS), "nodes": nodes,
                    "starts": vitals_history.starts(redis_store, since)})


def _pi_name(node: dict[str, Any]) -> str:
    kind = node.get("kind") or ""
    return {"koffer": "Koffer-Pi", "bad": "Bad-Pi"}.get(kind, "Pi")


def _record_pi_vitals() -> None:
    """Zeichnet alle 10 s die Werte beider Pis auf; Fehler hier duerfen nie stoeren."""
    while True:
        time.sleep(10)
        try:
            data = node_info.cluster_status()
            ts = now_ms()
            for n in [data["self"]] + ([data["peer"]] if data["peer"].get("reachable") else []):
                vitals_history.add_pi(redis_store, _pi_name(n), ts, n)
        except Exception:  # noqa: BLE001
            pass


@app.get("/api/taster")
def api_get_taster():
    st = load_state()
    return jsonify({"tasters": [_taster_with_vitals(t, st.get("vitals", {})) for t in st["tasters"]]})


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
    shutdown_active = now_ms() < int(st.get("shutdown_until_ms", 0) or 0)
    if not shutdown_active and not entry.get("letter"):
        used = {t.get("letter") for t in st["tasters"]}
        entry["letter"] = next((c for c in TASTER_LETTERS if c not in used), None)

    save_state(st)
    return jsonify({"ok": True, "taster": entry})


@app.get("/api/startcards")
def api_get_startcards() -> ResponseReturnValue:
    state = load_state()
    startcards = state.get("startcards", {})
    return jsonify(
        {
            **startcards,
            "rows": startcards.get("rows", []),
            "max_lane": startcards.get("max_lane", 0),
            "runs": startcards.get("runs", []),
            "error": startcards.get("last_error"),
        }
    )


@app.post("/api/startcards/reload")
def api_reload_startcards() -> tuple[ResponseReturnValue, int]:
    state = load_state()

    payload = request.get_json(force=True, silent=True) or {}
    settings = state.get("settings", {})
    base_url = str(
        payload.get("base_url", settings.get("startcards_base_url", "")) or ""
    ).strip()
    suffix = str(payload.get("suffix", settings.get("startcards_suffix", "")) or "").strip()
    if not base_url:
        state["startcards"]["last_error"] = "base_url_missing"
        save_state(state)
        return jsonify({"ok": False, "error": "base_url_missing"}), 400

    if not suffix:
        state["startcards"]["last_error"] = "suffix_missing"
        save_state(state)
        return jsonify({"ok": False, "error": "suffix_missing"}), 400
    settings["startcards_base_url"] = base_url
    settings["startcards_suffix"] = suffix
    state["settings"] = settings
    save_state(state)

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

        # Encoding-Erkennung (wichtig fÃ¼r Umlaute in Namen)
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


OTA_KEY: Final[str] = "OTA_TARGET"
OTA_CONFIRM_TEXT: Final[str] = "UPDATE"


def _competition_started(st: State) -> bool:
    """True, sobald im Wettkampf irgendein Lauf gestartet wurde."""
    return any(bool((p or {}).get(STARTER_KEY)) for p in (st.get("triggers_per_run") or {}).values())


def _load_ota() -> Optional[dict[str, Any]]:
    try:
        raw = redis_store.get(OTA_KEY)
    except redis.RedisError:  # Anzeige und Trigger duerfen nie am Update-Zustand haengen
        return None
    return json.loads(raw) if raw else None


def _ota_offer_for(st: State, mac: str) -> dict[str, Any]:
    """Firmware-Angebot fuer einen Taster (Felder von /api/display); leer, wenn keins ansteht."""
    target = _load_ota()
    if not target or not mac or mac not in target.get("macs", []):
        return {}
    if (target.get("status") or {}).get(mac, {}).get("state") == "failed":
        return {}
    fw = ((st.get("vitals") or {}).get(mac) or {}).get("fw")
    if fw == target["tag"] or _run_in_progress(st):
        return {}
    return {"ota_version": target["tag"], "ota_md5": target["md5"], "ota_size": target["size"]}


def _load_wifi_cfg() -> Optional[dict[str, Any]]:
    try:
        return wifi_config.load(redis_store)
    except redis.RedisError:
        return None


def _wifi_offer_for(st: State, mac: str) -> dict[str, Any]:
    """Neue WLAN-Daten nur an bekannte Taster, bis sie den Empfang bestaetigt haben."""
    if not mac or not any(t.get("mac") == mac for t in st.get("tasters", [])):
        return {}
    return wifi_config.offer_for(_load_wifi_cfg(), (st.get("vitals") or {}).get(mac))


@app.get("/api/wifi-config")
def api_wifi_config_get():
    cfg = _load_wifi_cfg()
    st = load_state()
    cluster = node_info.cluster_status()
    pis = [n for n in (cluster.get("self"), cluster.get("peer")) if n and n.get("reachable")]
    out: dict[str, Any] = {
        "configured": cfg is not None,
        "confirm_text": OTA_CONFIRM_TEXT,
        "competition_started": _competition_started(st),
        "run_in_progress": _run_in_progress(st),
        "pis": [
            {"hostname": n.get("hostname"), "kind": n.get("kind"), "applied_ver": n.get("wifi_applied_ver", 0)}
            for n in pis
        ],
    }
    if cfg:
        out.update({
            "version": cfg["version"],
            "ssid1": cfg["wifi1"]["ssid"],
            "ssid2": cfg["wifi2"]["ssid"],
            "force": bool(cfg.get("force")),
            "tasters": wifi_config.taster_status(cfg, st, now_ms()),
        })
    return jsonify(out)


@app.post("/api/wifi-config")
def api_wifi_config_set():
    """Neue WLAN-Daten speichern. Taster holen sie ab; die Pis stellen erst danach um."""
    body = request.get_json(silent=True) or {}
    st = load_state()
    if _run_in_progress(st):
        return jsonify({"ok": False, "error": "Ein Lauf laeuft gerade"}), 409
    if _competition_started(st) and str(body.get("confirm", "")) != OTA_CONFIRM_TEXT:
        return jsonify({"ok": False, "error": "locked", "confirm_text": OTA_CONFIRM_TEXT}), 409
    old = _load_wifi_cfg() or {}
    nets: list[dict[str, str]] = []
    for idx in (1, 2):
        ssid = str(body.get(f"ssid{idx}", "")).strip()
        psk = str(body.get(f"psk{idx}", "")) or (old.get(f"wifi{idx}") or {}).get("psk", "")
        problem = wifi_config.validate_ssid(ssid) or wifi_config.validate_psk(psk)
        if problem:
            return jsonify({"ok": False, "error": f"{'Koffer' if idx == 1 else 'Bad'}-WLAN: {problem}"}), 400
        nets.append({"ssid": ssid, "psk": psk})
    if nets[0]["ssid"] == nets[1]["ssid"]:
        return jsonify({"ok": False, "error": "Koffer- und Bad-WLAN brauchen verschiedene Namen"}), 400
    if old and (old["wifi1"], old["wifi2"]) == (nets[0], nets[1]):
        return jsonify({"ok": False, "error": "Keine Aenderung"}), 400
    try:
        cfg = wifi_config.save(redis_store, nets[0], nets[1])
    except redis.ReadOnlyError:
        return jsonify({"ok": False, "error": "Dieser Pi ist gerade nur Kopie (Redis schreibgeschÃ¼tzt)"}), 503
    logger.warning("Neue WLAN-Daten gespeichert (Fassung %s)", cfg["version"])
    return jsonify({"ok": True, "version": cfg["version"]})


@app.post("/api/wifi-config/force")
def api_wifi_config_force():
    """Pis sofort umstellen, auch wenn nicht alle Taster bestaetigt haben."""
    if _run_in_progress(load_state()):
        return jsonify({"ok": False, "error": "Ein Lauf laeuft gerade"}), 409
    if not _load_wifi_cfg():
        return jsonify({"ok": False, "error": "Keine WLAN-Daten gespeichert"}), 400
    wifi_config.set_force(redis_store)
    return jsonify({"ok": True})


@app.get("/api/firmware/releases")
def api_firmware_releases():
    """Verfuegbare Firmware-Versionen (GitHub, sonst nur lokal gespeicherte) und Stand der Verteilung."""
    st = load_state()
    cached = firmware_store.cached_tags()
    error = None
    releases: list[dict[str, Any]] = []
    try:
        releases = firmware_store.list_releases_cached()
        releases = [dict(r) for r in releases]
    except Exception as exc:  # Netzwerk, JSON, Rate-Limit
        error = f"GitHub nicht erreichbar: {exc}"
        releases = [{"tag": t, "published": None, "size": None} for t in cached]
    for r in releases:
        r["cached"] = r["tag"] in cached
        r.pop("url", None)
    tasters = []
    for t in st.get("tasters", []):
        info = _taster_with_vitals(t, st.get("vitals") or {})
        tasters.append({k: info.get(k) for k in ("mac", "name", "letter", "fw", "online", "battery")})
    target = _load_ota()
    return jsonify(
        {
            "releases": releases,
            "error": error,
            "tasters": tasters,
            "target": target,
            "competition_started": _competition_started(st),
            "run_in_progress": _run_in_progress(st),
            "confirm_text": OTA_CONFIRM_TEXT,
        }
    )


@app.post("/api/firmware/deploy")
def api_firmware_deploy():
    """Gewaehlte Version laden und allen Tastern anbieten, die gerade online sind."""
    body = request.get_json(silent=True) or {}
    tag = str(body.get("tag", ""))
    if firmware_store.parse_tag(tag) is None:
        return jsonify({"ok": False, "error": "Ungueltige Version"}), 400
    st = load_state()
    if _competition_started(st) and str(body.get("confirm", "")) != OTA_CONFIRM_TEXT:
        return jsonify({"ok": False, "error": "locked", "confirm_text": OTA_CONFIRM_TEXT}), 409
    info = firmware_store.file_info(tag)
    if info is None:
        try:
            release = next((r for r in firmware_store.list_releases() if r["tag"] == tag), None)
            if release is None:
                return jsonify({"ok": False, "error": "Version nicht gefunden"}), 404
            info = firmware_store.download(tag, release["url"])
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Download fehlgeschlagen: {exc}"}), 502
    macs = [
        t["mac"]
        for t in (_taster_with_vitals(t, st.get("vitals") or {}) for t in st.get("tasters", []))
        if t.get("online") and t.get("fw") != tag
    ]
    target = {"tag": tag, "md5": info["md5"], "size": info["size"], "macs": macs, "status": {}, "ts": now_ms()}
    redis_store.set(OTA_KEY, json.dumps(target))
    logger.info("Firmware %s fuer %d Taster freigegeben", tag, len(macs))
    return jsonify({"ok": True, "target": target})


@app.post("/api/firmware/cancel")
def api_firmware_cancel():
    redis_store.delete(OTA_KEY)
    return jsonify({"ok": True})


@app.get("/api/firmware/download")
def api_firmware_download():
    """Firmware-Datei fuer einen Taster, dem ein Update angeboten wurde."""
    st = load_state()
    mac = request.args.get("mac", "").strip()
    if not _ota_offer_for(st, mac):
        abort(404)
    target = _load_ota()
    path = firmware_store.cached_file(target["tag"]) if target else None
    if path is None:
        abort(404)
    return send_file(path, mimetype="application/octet-stream", conditional=False)


@app.post("/api/ota-status")
def api_ota_status():
    """Fehlermeldung eines Tasters zum Update (Erfolg zeigt sich an der neuen Version)."""
    body = request.get_json(silent=True) or {}
    mac = str(body.get("mac", "")).strip()
    target = _load_ota()
    if not target or mac not in target.get("macs", []):
        return jsonify({"ok": True})
    if not body.get("ok", False):
        target.setdefault("status", {})[mac] = {"state": "failed", "msg": str(body.get("msg", ""))[:60]}
        redis_store.set(OTA_KEY, json.dumps(target))
        logger.warning("Firmware-Update von %s fehlgeschlagen: %s", mac, body.get("msg"))
    return jsonify({"ok": True})


@app.get("/api/pi-update/releases")
def api_pi_update_releases():
    """Verfuegbare Software-Versionen (Git-Tags) des Pi."""
    st = load_state()
    base = {
        "version": APP_VERSION,
        "competition_started": _competition_started(st),
        "run_in_progress": _run_in_progress(st),
        "confirm_text": OTA_CONFIRM_TEXT,
    }
    if not pi_update.available():
        return jsonify({**base, "supported": False, "tags": [], "error": "Kein Git-Checkout (Docker?)", "current": {}})
    try:
        tags, error = pi_update.list_tags()
    except Exception as exc:
        tags, error = [], str(exc)
    return jsonify({**base, "supported": True, "tags": tags, "error": error, "current": pi_update.current()})


@app.post("/api/pi-update/deploy")
def api_pi_update_deploy():
    """Auf die gewaehlte Version wechseln und den Dienst neu starten (systemd startet ihn wieder)."""
    body = request.get_json(silent=True) or {}
    tag = str(body.get("tag", ""))
    if pi_update.parse_tag(tag) is None:
        return jsonify({"ok": False, "error": "Ungueltige Version"}), 400
    if not pi_update.available():
        return jsonify({"ok": False, "error": "Kein Git-Checkout (Docker?)"}), 400
    st = load_state()
    if _run_in_progress(st):
        return jsonify({"ok": False, "error": "Ein Lauf laeuft gerade"}), 409
    if _competition_started(st) and str(body.get("confirm", "")) != OTA_CONFIRM_TEXT:
        return jsonify({"ok": False, "error": "locked", "confirm_text": OTA_CONFIRM_TEXT}), 409
    try:
        commit = pi_update.switch_to(tag)
    except Exception as exc:
        logger.error("Pi-Update auf %s fehlgeschlagen: %s", tag, exc)
        return jsonify({"ok": False, "error": f"Wechsel fehlgeschlagen: {exc}"}), 500
    logger.warning("Pi-Software auf %s (%s) gewechselt, Neustart", tag, commit)
    # Antwort erst ausliefern, dann beenden; systemd (Restart=always) startet den Dienst neu
    threading.Timer(1.0, os._exit, args=(0,)).start()
    return jsonify({"ok": True, "tag": tag, "commit": commit, "restarting": True})


@app.get("/api/cluster-status")
def api_cluster_status():
    """Zustand beider Pis (Zwei-Pi-Betrieb) inkl. Taster je WLAN."""
    st = load_state()
    per_wifi: dict[str, int] = defaultdict(int)
    for t in st.get("tasters", []):
        v = (st.get("vitals") or {}).get(t.get("mac")) or {}
        online = bool(v.get("ts")) and now_ms() - int(v["ts"]) <= TASTER_ONLINE_TIMEOUT_MS
        if online:
            per_wifi[v.get("ssid") or "unbekannt"] += 1
    data = node_info.cluster_status()
    data["tasters_per_wifi"] = dict(per_wifi)
    data["version"] = APP_VERSION
    return jsonify(data)


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


def _record_finish_press(st: State, run_key: str, mac: str, ts: int) -> ResponseReturnValue:
    """Sammelt einen Druck des Zieleinlauf-Tasters; ohne gestarteten Lauf wird er ignoriert."""
    presses = (st.get("triggers_per_run") or {}).get(run_key) or {}
    if not presses.get(STARTER_KEY):
        return jsonify({"ok": True, "ignored": True, "reason": "not_started"})
    collected = st.setdefault("finish_per_run", {}).setdefault(run_key, [])
    if collected and any(abs(ts - int(p["ts"])) < finish_module.DEBOUNCE_MS for p in collected):
        return jsonify({"ok": True, "ignored": True, "reason": "debounce"})
    collected.append({"ts": ts, "mac": mac})
    save_state(st)
    return jsonify({"ok": True, "finish": True, "index": len(collected) - 1, "run_key": run_key})


def _finish_info(st: State, run_key: str) -> Optional[dict[str, Any]]:
    """Zieleinlauf-Zeiten eines Versuchs samt Zuordnung zu den Bahnen (None ohne Druecke)."""
    collected = (st.get("finish_per_run") or {}).get(run_key) or []
    presses = (st.get("triggers_per_run") or {}).get(run_key) or {}
    starter = presses.get(STARTER_KEY)
    if not collected or not starter:
        return None
    starter_ts = int(starter["ts"])
    times = finish_module.finish_times(starter_ts, collected)
    manual = dict(((st.get("finish_assign") or {}).get(run_key) or {}))
    lane_times = {
        str(lane): int(p["ts"]) - starter_ts
        for lane, p in presses.items()
        if lane != STARTER_KEY and p and p.get("src") != FINISH_KEY
    }
    matches = finish_module.match(
        lane_times, times, manual, (st.get("finish_parked") or {}).get(run_key) or []
    )
    return {
        "times_ms": times,
        "matches": matches,
        "unassigned": finish_module.unassigned(times, matches),
    }


@app.post("/api/finish/assign")
def api_post_finish_assign():
    """
    Ordnet einen Zieleinlauf-Druck haendlich einer Bahn zu (index), hebt die Zuordnung der Bahn auf
    (index = null) oder parkt den Druck (lane = "park"). Eine Bahn, die schon eine Zeit hat, gibt diese
    dabei in den Parkplatz ab.

    Nur zum Vergleichen: die Bahnzeit des Laufs aendert sich dadurch nicht (siehe /api/finish/transfer).
    Payload: { "run_key": "3", "lane": "2" | "park", "index": 0 | null }
    """
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    run_key = str(payload.get("run_key") or "")
    lane = str(payload.get("lane") or "")
    index = payload.get("index")
    if not run_key or not (lane.isdigit() or lane == "park"):
        return jsonify({"ok": False, "error": "missing run_key or lane"}), 400
    collected = (st.get("finish_per_run") or {}).get(run_key) or []
    manual = st.setdefault("finish_assign", {}).setdefault(run_key, {})
    parked = st.setdefault("finish_parked", {}).setdefault(run_key, [])
    valid_index = isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(collected)

    if lane == "park" or index is None:
        if lane == "park":
            if not valid_index:
                return jsonify({"ok": False, "error": "invalid index"}), 400
            for other, value in list(manual.items()):
                if value == index:
                    del manual[other]
            if index not in parked:
                parked.append(index)
        else:
            # Zuordnung der Bahn aufheben: Zeit parken, damit sie nicht gleich wieder automatisch greift
            info = _finish_info(st, run_key)
            current = ((info or {}).get("matches") or {}).get(lane)
            manual.pop(lane, None)
            if current and current["index"] not in parked:
                parked.append(current["index"])
    else:
        if not valid_index:
            return jsonify({"ok": False, "error": "invalid index"}), 400
        info = _finish_info(st, run_key)
        displaced = ((info or {}).get("matches") or {}).get(lane)
        for other, value in list(manual.items()):
            if value == index:
                del manual[other]
        if index in parked:
            parked.remove(index)
        if displaced and displaced["index"] != index and displaced["index"] not in parked:
            parked.append(displaced["index"])
        manual[lane] = index
    save_state(st)
    return jsonify({"ok": True})


@app.post("/api/finish/transfer")
def api_post_finish_transfer():
    """
    Uebertraegt die Zieleinlauf-Zeiten eines Versuchs als NEUE Laufversion (z. B. 5/2, beim naechsten Mal 5/3).

    Bahnen mit zugeordneter Zieleinlauf-Zeit bekommen diese, alle anderen Bahnen ihre normal gestoppte Zeit.
    Die Version geht in die Ergebnisdatei fuer JAuswertung; die Bahnzeiten des Versuchs bleiben unveraendert.
    Payload: { "run_key", "undo": true (= zuletzt uebertragene Version zuruecknehmen) }
    """
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    run_key = str(payload.get("run_key") or "")
    parsed = _parse_attempt_key(run_key)
    if parsed is None:
        return jsonify({"ok": False, "error": "missing run_key"}), 400
    adopted_all = st.setdefault("finish_adopted", {})
    versions = _adopted_versions(st, run_key)
    adopted_all[run_key] = versions

    if payload.get("undo"):
        if versions:
            versions.pop()
    else:
        info = _finish_info(st, run_key)
        matches = (info or {}).get("matches") or {}
        if not matches:
            return jsonify({"ok": False, "error": "Keine Zieleinlauf-Zeit einer Bahn zugeordnet."}), 400
        presses = (st.get("triggers_per_run") or {}).get(run_key) or {}
        starter_ts = int(presses[STARTER_KEY]["ts"])
        lanes = {
            str(lane): int(p["ts"]) - starter_ts
            for lane, p in presses.items()
            if lane != STARTER_KEY and p
        }
        for lane, m in matches.items():
            lanes[lane] = info["times_ms"][m["index"]]
        versions.append({"attempt": _next_attempt(st, parsed[0]), "lanes": lanes, "assigned": sorted(matches)})
    if not versions:
        adopted_all.pop(run_key, None)
    save_state(st)
    _write_heats_xml(st)
    return jsonify({"ok": True, "label": _attempt_key(parsed[0], versions[-1]["attempt"]) if versions else None})


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

    current_attempt = int(st.get("current_attempt") or 1)
    current_key = _attempt_key(int(current_run), current_attempt)
    ts_val = int(payload.get("ts", now_ms()))

    if test_lane is not None:
        mac_norm = "test"
        lane = str(test_lane)
        ts_val = now_ms()
    else:
        mac_norm = str(mac).strip()
        if _is_range_test_taster(st, mac_norm):
            return jsonify({"ok": True, "ignored": True, "reason": "range_test"})
        lane = _lane_for_mac(st, mac_norm)
        # Zeitstempel des Tasters auf die Serveruhr umrechnen. Kleine Versaetze sind nur
        # Netzwerklatenz (je Taster verschieden) und wuerden die Zeiten verfaelschen; korrigiert
        # wird nur bei grober Abweichung (Taster nicht auf Serverzeit synchronisiert).
        offset = int((st.get("clock_offsets") or {}).get(mac_norm, 0))
        if abs(offset) > CLOCK_OFFSET_MIN_MS:
            ts_val += offset

    if lane is None:
        swapped = _try_pending_swap(st, mac_norm)
        if swapped == "waiting":
            return jsonify({"ok": True, "ignored": True, "reason": "swap_waiting_for_run_end"})
        if swapped is not None:
            save_state(st)
            return jsonify({"ok": True, "swapped": True, "lane": swapped})
        return jsonify({"ok": False, "error": f"no lane found for mac {mac_norm}"}), 400

    if lane == FINISH_KEY:
        return _record_finish_press(st, current_key, mac_norm, ts_val)

    # Kombirolle Starter/Zieleinlauf: der erste Druck startet, jeder weitere ist ein Zieleinlauf-Druck
    # (auch kurz nach dem Lauf-Ende, damit der letzte Anschlag nicht den naechsten Lauf startet)
    if lane == STARTER_KEY and str(st.get("settings", {}).get("starter_is_finish", "0")) == "1":
        started = (st.get("triggers_per_run") or {}).get(current_key, {}).get(STARTER_KEY)
        done_ts = st.get("run_finished_ts")
        recently_done = done_ts is not None and now_ms() - int(done_ts) < STARTER_FINISH_GRACE_MS
        if started and (done_ts is None or recently_done):
            return _record_finish_press(st, current_key, mac_norm, ts_val)

    if lane == STARTER_KEY:
        locked_until = int(st.get("start_locked_until_ms", 0) or 0)
        if now_ms() < locked_until:
            remaining_ms = locked_until - now_ms()
            return jsonify(
                {
                    "ok": False,
                    "error": "Start nach Abbruch noch gesperrt.",
                    "lockout_remaining_s": (remaining_ms + 999) // 1000,
                }
            ), 423

    # Starter-Druck nach abgeschlossenem Lauf startet sofort den naechsten Lauf
    if lane == STARTER_KEY and st.get("run_finished_ts") is not None:
        _advance_run(st)
        current_run = st["current_run"]
        current_attempt = int(st.get("current_attempt") or 1)
        current_key = _attempt_key(int(current_run), current_attempt)

    lanes_in_run = [v["Bahn"] for v in st.get("startcards_per_run", {}).get(str(current_run), [])]
    triggers_per_run = st.get("triggers_per_run") or {}
    triggers_per_run.setdefault(current_key, {})
    # Zweiter Starter-Druck bei laufender Uhr: Lauf beenden (Bahnen ohne Zeit bleiben leer)
    first_start = triggers_per_run[current_key].get(STARTER_KEY) if lane == STARTER_KEY else None
    if first_start:
        if ts_val - int(first_start["ts"]) < STARTER_STOP_MIN_MS:
            return jsonify({"ok": True, "ignored": True, "reason": "double_press_too_fast"})
        stopped = set(st.get("stopped_by_starter") or [])
        stopped.add(current_key)
        st["stopped_by_starter"] = sorted(stopped)
        st["run_finished_ts"] = now_ms()
        save_state(st)
        _write_heats_xml(st)
        logger.info(f"Run {current_key} stopped by second starter press")
        return jsonify({"ok": True, "stopped": True, "run_key": current_key})
    triggers_per_run[current_key].setdefault(lane, None)
    # Abort press if the run has not been started yet.
    if lane != STARTER_KEY and not any(
        p == STARTER_KEY for p in triggers_per_run[current_key].keys()
    ):
        return jsonify({"ok": False, "error": "Run has not started yet."}), 400
    # Stopp-Sperre: Bahn-Signale kurz nach dem Start werden ignoriert (z. B. Fehlausloesungen)
    if lane != STARTER_KEY:
        starter_press = triggers_per_run[current_key].get(STARTER_KEY)
        lockout_ms = _stop_lockout_ms(st)
        if starter_press and ts_val - int(starter_press["ts"]) < lockout_ms:
            logger.info(f"Stop signal of lane {lane} ignored (lockout {lockout_ms} ms)")
            return jsonify({"ok": True, "ignored": True, "reason": "stop_lockout"})
    # Abort double press
    if triggers_per_run[current_key][lane]:
        return jsonify({"ok": False, "error": "Double press detected."}), 400
    # Reject lanes which are not in the current run, except STARTER
    if lane != STARTER_KEY and lane not in lanes_in_run:
        abort(400, description=f"Lane {lane} is not in the current run.")
    press: PressEvent = {
        "ts": ts_val,
        "mac": mac_norm,
    }

    triggers_per_run[current_key][lane] = press
    st["triggers_per_run"] = triggers_per_run
    save_state(st)
    if lane == STARTER_KEY:
        vitals_history.add_start(redis_store, ts_val, current_key)
    # Check, if for all lanes presses have been received
    if lanes_in_run and not (set(lanes_in_run) - set(triggers_per_run[current_key].keys())):
        logger.info(f"All lanes have been pressed in run {current_key}")
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
                "attempt": current_attempt,
                "run_key": current_key,
                "lane": lane,
            },
        }
    )


def _display_text(text: Any, limit: int = 30) -> str:
    """Bereinigt Anzeigetext und erhÃ¤lt Umlaute als UTF-8."""
    s = unicodedata.normalize("NFC", str(text or ""))
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
    attempt = int(st.get("current_attempt") or 1)
    run_key = _attempt_key(run, attempt)
    cards = (st.get("startcards_per_run") or {}).get(str(run), [])
    all_presses = st.get("triggers_per_run") or {}
    presses = all_presses.get(run_key) or {}
    starter = presses.get(STARTER_KEY)
    now = now_ms()
    finished = st.get("run_finished_ts") is not None

    out: dict[str, Any] = {
        "role": "none",
        "shutdown": now < int(st.get("shutdown_until_ms", 0) or 0),
        "low_battery_pct": _int_setting(st, "low_battery_pct", 10),
        "low_battery_min": _int_setting(st, "low_battery_min", 5),
        "lane": None,
        "run": run,
        "attempt": attempt,
        "state": "ready",
        "server_now": now,
        "elapsed_ms": None,
        "time_ms": None,
        "name": "",
        "discipline": "",
        "last_ms": None,
        "last_name": "",
        "last_run": None,
        "last_attempt": None,
        "start_locked_until_ms": int(st.get("start_locked_until_ms", 0) or 0),
    }
    out.update(_ota_offer_for(st, mac))
    out.update(_wifi_offer_for(st, mac))
    if mac and _is_range_test_taster(st, mac):
        # Funktest: Taster zeigt nur die Signalstaerke (Rolle "range"); die Schwellen stammen aus den Grenzwerten
        warn, crit = limits_module.merged(st.get("settings", {}).get("limits"))["taster"]["rssi"]["values"]
        out["role"] = "range"
        out["rssi_warn"] = int(warn)
        out["rssi_crit"] = int(crit)
        return jsonify(out)
    if lane is None:
        pending_lane = next(
            (k for k, v in ((st.get("assignments") or {}).get("pending") or {}).items() if v == mac),
            None,
        )
        out["pending_lane"] = pending_lane or ""
        return jsonify(out)

    previous_attempts = []
    if lane == FINISH_KEY:
        # Wie der Starter, aber Zeile i zeigt den i-ten Druck des Zieleinlaufs (Anzahl = Bahnen des Laufs)
        out["role"] = "finish"
        out["name"] = _display_text(f"{len(cards)} Schwimmer") if cards else ""
        out["discipline"] = _display_text(cards[0].get("Disziplin")) if cards else ""
        collected = (st.get("finish_per_run") or {}).get(run_key) or []
        count = len({str(c.get("Bahn")) for c in cards if str(c.get("Bahn")).isdigit()})
        parts = []
        for i in range(count):
            if i < len(collected) and starter:
                parts.append(f"{i + 1},s,{max(0, int(collected[i]['ts']) - int(starter['ts']))}")
            else:
                parts.append(f"{i + 1},{'r' if starter and not finished else 'w'},-1")
        out["lanes"] = ";".join(parts)
        if starter:
            if finished:
                out["state"] = "stopped"
                out["time_ms"] = max(
                    (max(0, int(p["ts"]) - int(starter["ts"])) for p in collected), default=0
                )
            else:
                out["state"] = "running"
                out["elapsed_ms"] = max(0, now - int(starter["ts"]))
        return jsonify(out)
    for key, previous_presses in all_presses.items():
        parsed = _parse_attempt_key(key)
        if parsed is None or not previous_presses or key == run_key:
            continue
        previous_run, previous_attempt = parsed
        previous_starter = previous_presses.get(STARTER_KEY)
        if previous_run <= run and previous_starter:
            previous_attempts.append(
                (int(previous_starter.get("ts", 0)), previous_run, previous_attempt, previous_presses)
            )
    previous_attempts.sort(reverse=True, key=lambda value: value[0])

    if lane == STARTER_KEY:
        out["role"] = "starter"
        out["name"] = _display_text(f"{len(cards)} Schwimmer") if cards else ""
        out["discipline"] = _display_text(cards[0].get("Disziplin")) if cards else ""
        # Alle Bahnen des Laufs: "bahn,zustand,ms;..." (w wartet, r laeuft, s gestoppt; ms nur bei s)
        parts = []
        for ln in sorted({str(c.get("Bahn")) for c in cards if str(c.get("Bahn")).isdigit()}, key=int):
            t = _lane_time(presses, ln)
            if t is not None:
                parts.append(f"{ln},s,{t}")
            else:
                parts.append(f"{ln},{'r' if starter and not finished else 'w'},-1")
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
        for _, previous_run, previous_attempt, previous_presses in previous_attempts:
            times = [t for ln in previous_presses if ln != STARTER_KEY
                     if (t := _lane_time(previous_presses, ln)) is not None]
            if times:
                out["last_ms"], out["last_run"], out["last_attempt"] = max(times), previous_run, previous_attempt
                break
        return jsonify(out)

    out["role"] = "lane"
    out["lane"] = int(lane) if str(lane).isdigit() else None
    card = next((c for c in cards if str(c.get("Bahn")) == str(lane)), None)
    if card is None:
        out["state"] = "inactive"
        out["name"] = "frei"
    else:
        out["name"] = _display_text(card.get("Name"))
        out["discipline"] = _display_text(card.get("Disziplin"))
        stopped = _lane_time(presses, str(lane))
        if stopped is not None:
            out["state"], out["time_ms"] = "stopped", stopped
        elif starter and not finished:
            out["state"] = "running"
            out["elapsed_ms"] = max(0, now - int(starter["ts"]))
    for _, previous_run, previous_attempt, previous_presses in previous_attempts:
        t = _lane_time(previous_presses, str(lane))
        if t is not None:
            prev_card = next(
                (c for c in (st.get("startcards_per_run") or {}).get(str(previous_run), [])
                 if str(c.get("Bahn")) == str(lane)), None)
            out["last_ms"], out["last_run"], out["last_attempt"] = t, previous_run, previous_attempt
            out["last_name"] = _display_text((prev_card or {}).get("Name"))
            break
    return jsonify(out)


@app.get("/api/run-status")
def api_get_run_status():
    """Aktueller Lauf sowie je Lauf Starter-Zeitstempel und gemessene Zeiten (ms) je Bahn."""
    st = load_state()
    _maybe_advance_run(st)
    runs: dict[str, Any] = {}
    current_run = int(st.get("current_run") or 0)
    current_attempt = int(st.get("current_attempt") or 1)
    current_key = _attempt_key(current_run, current_attempt)
    stopped_keys = set(st.get("stopped_by_starter") or [])
    for run_key, presses in (st.get("triggers_per_run") or {}).items():
        starter = (presses or {}).get(STARTER_KEY)
        starter_ts = starter.get("ts") if starter else None
        times: dict[str, int] = {}
        if isinstance(starter_ts, int):
            for lane, press in presses.items():
                if lane == STARTER_KEY or not press:
                    continue
                times[str(lane)] = press["ts"] - starter_ts
        adopted = _adopted_versions(st, run_key)
        runs[str(run_key)] = {
            "started": starter_ts is not None,
            "starter_ts": starter_ts,
            "times_ms": times,
            "running": starter_ts is not None and run_key == current_key and st.get("run_finished_ts") is None,
            "stopped_by_starter": run_key in stopped_keys,
            "finish": _finish_info(st, run_key),
            "adopted": [
                {"label": _attempt_key(_parse_attempt_key(run_key)[0], v["attempt"]), "lanes": v["lanes"]}
                for v in adopted
            ] if _parse_attempt_key(run_key) else [],
        }
    finished = st.get("run_finished_ts")
    next_in = None
    if finished is not None:
        next_in = max(0, _auto_next_delay_ms(st) - (now_ms() - int(finished))) / 1000
    lockout_remaining = max(
        0, int(st.get("start_locked_until_ms", 0) or 0) - now_ms()
    ) / 1000
    return jsonify(
        {
            "current_run": current_run,
            "current_attempt": current_attempt,
            "current_key": current_key,
            "current_label": current_key,
            "start_lockout_remaining_s": lockout_remaining,
            "server_now": now_ms(),
            "next_run_in_s": next_in,
            "runs": runs,
        }
    )


@app.post("/api/current-run")
def api_post_current_run():
    """Bereitet einen neuen Versuch vor, ohne bereits gemessene Zeiten zu verÃ¤ndern."""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    try:
        run = int(payload.get("run"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "invalid run"}), 400
    if run < 1:
        return jsonify({"ok": False, "error": "invalid run"}), 400
    attempt = _prepare_attempt(st, run)
    save_state(st)
    _write_heats_xml(st)
    return jsonify(
        {
            "ok": True,
            "current_run": run,
            "current_attempt": attempt,
            "current_key": _attempt_key(run, attempt),
            "start_locked_until_ms": st["start_locked_until_ms"],
        }
    )


@app.post("/api/abort-run")
def api_post_abort_run():
    """Bricht den laufenden Versuch ab und bereitet eine neue Version desselben Laufs vor."""
    st = load_state()
    payload = request.get_json(force=True, silent=True) or {}
    mac = str(payload.get("mac") or "").strip()
    request_id = str(payload.get("request_id") or "").strip()
    if not mac or not request_id:
        return jsonify({"ok": False, "error": "missing mac or request_id"}), 400
    if _lane_for_mac(st, mac) != STARTER_KEY:
        return jsonify({"ok": False, "error": "abort is only available on the starter"}), 403

    requests = st.setdefault("abort_requests", {})
    previous = requests.get(mac)
    if previous and previous.get("request_id") == request_id:
        return jsonify(
            {
                "ok": True,
                "current_run": previous["run"],
                "current_attempt": previous["attempt"],
                "current_key": previous["key"],
            }
        )

    run = int(st.get("current_run") or 0)
    attempt = int(st.get("current_attempt") or 1)
    current_key = _attempt_key(run, attempt)
    current_presses = (st.get("triggers_per_run") or {}).get(current_key) or {}
    if not current_presses.get(STARTER_KEY) or st.get("run_finished_ts") is not None:
        return jsonify({"ok": False, "error": "no running attempt to abort"}), 409

    attempt = _prepare_attempt(st, run)
    key = _attempt_key(run, attempt)
    requests[mac] = {
        "request_id": request_id,
        "run": run,
        "attempt": attempt,
        "key": key,
    }
    st["abort_requests"] = requests
    save_state(st)
    _write_heats_xml(st)
    return jsonify(
        {
            "ok": True,
            "current_run": run,
            "current_attempt": attempt,
            "current_key": key,
            "start_locked_until_ms": st["start_locked_until_ms"],
        }
    )


@app.post("/api/test/reset-run")
def api_test_reset_run():
    """Nur zum Testen: Messung des aktuellen Laufs verwerfen."""
    st = load_state()
    run = int(st.get("current_run") or 0)
    attempt = int(st.get("current_attempt") or 1)
    run_key = _attempt_key(run, attempt)
    (st.get("triggers_per_run") or {}).pop(run_key, None)
    (st.get("finish_per_run") or {}).pop(run_key, None)
    (st.get("finish_assign") or {}).pop(run_key, None)
    (st.get("finish_parked") or {}).pop(run_key, None)
    (st.get("finish_adopted") or {}).pop(run_key, None)
    st["stopped_by_starter"] = [k for k in (st.get("stopped_by_starter") or []) if k != run_key]
    st["run_finished_ts"] = None
    save_state(st)
    return jsonify({"ok": True, "run": run_key})


def _heats_for_xml(st: State) -> list[tuple[int, int, dict[int, int]]]:
    """
    Versuche als (Laufnummer, Versuch, {Bahn: ms}) fuer JAuswertung.

    JAuswertung fuehrt die Laufnummer der Startkarten als <event>; Wiederholungsversuche
    werden als <heat> nummeriert (z. B. Lauf 5, Versuch 2 = 5/2).
    Ein Lauf gilt als fertig, wenn alle Bahnen eine Zeit
    haben oder der Lauf schon vor dem aktuellen liegt (Bahnen ohne Zeit fehlen dann).
    """
    cards_per_run = st.get("startcards_per_run") or {}
    event_of: dict[int, int] = {}
    for run, cards in cards_per_run.items():
        try:
            event_of[int(run)] = int(float((cards[0].get("Wettkampf") or 1)))
        except (ValueError, TypeError, IndexError):
            event_of[int(run)] = 1
    current = int(st.get("current_run") or 0)
    current_attempt = int(st.get("current_attempt") or 1)
    current_key = _attempt_key(current, current_attempt)
    heats = []
    for run_key, lane_times in determine_lane_times_per_run(st).items():
        parsed = _parse_attempt_key(run_key)
        if parsed is None:
            continue
        if run_key in (st.get("aborted_attempts") or []):
            continue
        run, attempt = parsed
        if run not in event_of or not lane_times:
            continue
        expected = {int(c["Bahn"]) for c in cards_per_run.get(str(run), []) if str(c.get("Bahn")).isdigit()}
        if (run > current or run_key == current_key) and not expected <= set(lane_times):
            continue
        heats.append((run, attempt, lane_times))
    # Uebernommene Zieleinlauf-Zeiten: je Uebertragung eine eigene Unterversion des Laufs
    for run_key in (st.get("finish_adopted") or {}):
        parsed = _parse_attempt_key(run_key)
        if parsed is None or parsed[0] not in event_of:
            continue
        for entry in _adopted_versions(st, run_key):
            if entry.get("lanes"):
                heats.append(
                    (parsed[0], int(entry["attempt"]), {int(lane): int(ms) for lane, ms in entry["lanes"].items()})
                )
    return sorted(heats, key=lambda heat: (heat[0], heat[1]))


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


LaneTimesPerRun = dict[str, dict[int, int]]  # run/attempt -> lane -> time_ms


def determine_lane_times_per_run(state: Optional[State] = None) -> LaneTimesPerRun:
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
    state = state or load_state()
    for run, presses_by_run in (state.get("triggers_per_run") or {}).items():
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

        run_times: dict[int, int] = {}
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

        lane_times[run] = run_times
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
    threading.Thread(target=_record_pi_vitals, daemon=True).start()
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
