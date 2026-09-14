from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Type

from .service import SummaryService


def handler_for(service: SummaryService) -> Type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "CLIProxyUsageBridge/0.1"

        def log_message(self, format: str, *args: object) -> None:
            # Do not log request headers or paths that could accidentally contain a secret.
            return

        def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json({"status": "ok", "schema_version": 1})
            elif self.path == "/api/v1/summary":
                self._json(service.get_summary())
            else:
                self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path != "/api/v1/refresh":
                self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            accepted = service.request_refresh()
            self._json({"status": "scheduled" if accepted else "debounced", "schema_version": 1}, HTTPStatus.ACCEPTED)

    return Handler


def serve(service: SummaryService) -> None:
    config = service.config
    if config.bind_host != "127.0.0.1":
        raise ValueError("refusing non-local bind")
    ThreadingHTTPServer((config.bind_host, config.bind_port), handler_for(service)).serve_forever()
