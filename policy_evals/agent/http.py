"""Adapter for any agent exposed as a JSON endpoint.

POSTs the request JSON from ``base.py`` and expects the response JSON back.
Anything else (refused connection, timeout, HTTP error, wrong shape) is
raised as AgentError or ResponseFormatError, which the runner records as a
failed case rather than crashing the run.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from .base import AgentError, AgentRequest, AgentResponse, ResponseFormatError


class HttpAgent:
    def __init__(self, url: str, timeout: float = 10.0, headers: dict | None = None):
        self.url = url
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        self.headers.update(headers or {})
        self.name = "http-agent"

    def describe(self) -> dict:
        # Header values may hold credentials, so only their names are reported.
        return {"name": self.name, "kind": "http", "url": self.url,
                "header_names": sorted(self.headers)}

    def ask(self, request: AgentRequest) -> AgentResponse:
        body = json.dumps(request.to_json()).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers=self.headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise AgentError(f"HTTP {exc.code} from {self.url}") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise AgentError(f"no reply from {self.url} within {self.timeout:g}s") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise AgentError(f"no reply from {self.url} within {self.timeout:g}s") from exc
            raise AgentError(f"cannot reach {self.url}: {exc.reason}") from exc
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResponseFormatError(f"reply from {self.url} is not JSON") from exc
        return AgentResponse.from_json(data)
