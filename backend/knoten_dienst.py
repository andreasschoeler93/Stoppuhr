"""Kleiner Dienst (Port 2000): liefert den Zustand dieses Pi als JSON unter /info.

Laeuft auf beiden Pis dauerhaft, damit der Partner den Zustand auch im Standby sieht.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import node_info


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


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", node_info.NODE_PORT), Handler).serve_forever()
