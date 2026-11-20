"""A small local HTTP server that exposes an agent as a JSON endpoint.

It is the stand-in for a hosted assistant, so the HTTP adapter is tested
against a real socket. Routes:

    POST /ask      the wrapped agent (the reference agent by default)
    POST /broken   a reply missing required fields
    POST /error    HTTP 500
    POST /slow     replies after ``slow_seconds``
    GET  /health   {"ok": true}
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .base import AgentRequest, ResponseFormatError

DEFAULT_PORT = 8104


class ExclusiveServer(ThreadingHTTPServer):
    """Refuses to start when the port is taken.

    On Windows, SO_REUSEADDR (which http.server sets) lets a second server
    bind a port that is already listening, and requests then reach the
    wrong one. Turning it off there makes a taken port fail loudly.
    """

    allow_reuse_address = os.name != "nt"
    daemon_threads = True


def make_server(agent, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                slow_seconds: float = 2.0) -> ExclusiveServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                self._send(200, {"ok": True, "agent": agent.describe()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "body is not JSON"})
                return
            if self.path == "/broken":
                self._send(200, {"answer": "I forgot the rest of the contract."})
            elif self.path == "/error":
                self._send(500, {"error": "internal error"})
            elif self.path == "/slow":
                time.sleep(slow_seconds)
                self._send(200, {"answer": "late", "action": "answer", "citations": []})
            elif self.path == "/ask":
                try:
                    req = AgentRequest.from_json(payload)
                except ResponseFormatError as exc:
                    self._send(400, {"error": str(exc)})
                    return
                self._send(200, agent.ask(req).to_json())
            else:
                self._send(404, {"error": "not found"})

        def log_message(self, *args):  # keep test and CLI output clean
            pass

    return ExclusiveServer((host, port), Handler)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return t
