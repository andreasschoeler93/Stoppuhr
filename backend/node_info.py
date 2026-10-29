"""Zustand eines Pi (Zwei-Pi-Betrieb).

Wird von der Stoppuhr (eigener Knoten, Partner abfragen) und vom kleinen
Dienst `knoten_dienst.py` benutzt. Der Dienst laeuft auf beiden Pis immer,
auch wenn die Stoppuhr dort gerade im Standby gestoppt ist.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.request
from typing import Any, Optional

import psutil
import redis

NODE_PORT = int(os.environ.get("NODE_PORT", "2000"))
ROLE_FILE = os.environ.get("ROLE_CHANGE_FILE", "/var/lib/stoppuhr-rollenwechsel")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=2).stdout.strip()
    except Exception:
        return ""


def _ipv4_addresses() -> dict[str, str]:
    """Alle IPv4-Adressen je Schnittstelle (mehrere, z. B. feste Adresse + VIP, kommagetrennt)."""
    out: dict[str, str] = {}
    for ifname, addrs in psutil.net_if_addrs().items():
        if ifname == "lo":
            continue
        found = [a.address for a in addrs if a.family == socket.AF_INET]
        if found:
            out[ifname] = ", ".join(found)
    return out


def _wifi_ssid() -> Optional[str]:
    """Name des WLANs, das dieser Pi bereitstellt (Zugangspunkt) bzw. an dem er haengt."""
    ssid = _run(["nmcli", "-t", "-g", "802-11-wireless.ssid", "connection", "show", "ap"])
    if ssid:
        return ssid
    for line in _run(["iw", "dev"]).splitlines():
        line = line.strip()
        if line.startswith("ssid "):
            return line[5:]
    return None


def _wifi_applied() -> int:
    try:
        with open(os.environ.get("WIFI_APPLIED_FILE", "/var/lib/stoppuhr-wlan-version")) as fh:
            return int(fh.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def _cpu_temp() -> Optional[float]:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as fh:
            return round(int(fh.read().strip()) / 1000, 1)
    except Exception:
        return None


def _redis_info() -> dict[str, Any]:
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=1, decode_responses=True)
        info = r.info("replication")
        return {
            "role": info.get("role"),
            "link": info.get("master_link_status"),
            "replicas": info.get("connected_slaves", 0),
        }
    except Exception:
        return {"role": None, "link": None, "replicas": 0}


def _last_role_change() -> Optional[dict[str, Any]]:
    try:
        with open(ROLE_FILE) as fh:
            ts, state = fh.read().split()[:2]
        return {"ts": int(ts) * 1000, "state": state}
    except Exception:
        return None


def collect() -> dict[str, Any]:
    vip = os.environ.get("VIP")
    addrs = _ipv4_addresses()
    mem = psutil.virtual_memory()
    return {
        "hostname": socket.gethostname(),
        "kind": os.environ.get("ROLLE", ""),  # koffer | bad | "" (Einzelbetrieb)
        "ips": addrs,
        "has_vip": bool(vip) and any(vip in v.split(", ") for v in addrs.values()),
        "vip": vip,
        "wifi_ssid": _wifi_ssid(),
        "wifi_applied_ver": _wifi_applied(),
        "uptime_s": int(time.time() - psutil.boot_time()),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "cpu_temp": _cpu_temp(),
        "mem_percent": mem.percent,
        "disk_percent": psutil.disk_usage("/").percent,
        "stoppuhr_active": _run(["systemctl", "is-active", "stoppuhr"]) == "active",
        "redis": _redis_info(),
        "last_role_change": _last_role_change(),
        "ts": int(time.time() * 1000),
    }


def fetch_peer() -> dict[str, Any]:
    """Zustand des Partner-Pi holen; bei Fehler ist er nicht erreichbar."""
    peer = os.environ.get("PEER_IP")
    if not peer:
        return {"reachable": False, "configured": False}
    try:
        with urllib.request.urlopen(f"http://{peer}:{NODE_PORT}/info", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        data["reachable"] = True
        data["configured"] = True
        data["peer_ip"] = peer
        return data
    except Exception:
        return {"reachable": False, "configured": True, "peer_ip": peer}


def cluster_status() -> dict[str, Any]:
    """Beide Pis fuer die Weboberflaeche: eigener Knoten plus Partner."""
    own = collect()
    own["reachable"] = True
    peer = fetch_peer()
    nodes = [own] + ([peer] if peer.get("configured") else [])
    active = next((n for n in nodes if n.get("reachable") and n.get("has_vip")), None)
    return {
        "two_pi": bool(peer.get("configured")),
        "self": own,
        "peer": peer,
        "active_hostname": active.get("hostname") if active else None,
        "active_kind": active.get("kind") if active else None,
    }
