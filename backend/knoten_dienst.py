"""Kleiner Dienst (Port 2000): liefert den Zustand dieses Pi als JSON unter /info.

Laeuft auf beiden Pis dauerhaft, damit der Partner den Zustand auch im Standby sieht.
"""

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import redis

import node_info
import wifi_config


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/info":
            self.send_error(404)
            return
        body = json.dumps(node_info.collect(), ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def wlan_loop() -> None:
    """Stellt den Zugangspunkt dieses Pi auf die neuen WLAN-Daten um, sobald die Taster sie haben."""
    r = redis.Redis(host="127.0.0.1", port=6379, socket_timeout=2, decode_responses=True)
    kind = os.environ.get("ROLLE", "")
    retry_after = 0.0
    while True:
        time.sleep(5)
        try:
            cfg = wifi_config.load(r)
            if not cfg or wifi_config.applied_version() >= cfg["version"] or time.time() < retry_after:
                continue
            raw = r.get("STATE")
            state = json.loads(raw) if raw else {}
            if not wifi_config.ready_for_pi(cfg, state, int(time.time() * 1000)):
                continue
            error = wifi_config.apply_to_pi(cfg, kind)
            if error:
                print(f"WLAN umstellen fehlgeschlagen: {error}", flush=True)
                retry_after = time.time() + 60
        except Exception as exc:  # der Dienst darf wegen eines Fehlers hier nie enden
            print(f"WLAN-Abgleich: {exc}", flush=True)


if __name__ == "__main__":
    threading.Thread(target=wlan_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", node_info.NODE_PORT), Handler).serve_forever()
