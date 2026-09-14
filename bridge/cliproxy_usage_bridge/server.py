from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Type

from .service import SummaryService


_MAX_CONFIG_BODY_BYTES = 16 * 1024


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

        def _config_request(self) -> dict[str, object] | None:
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return None
            if length < 0 or length > _MAX_CONFIG_BODY_BYTES:
                self._json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return None
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return None
            if not isinstance(payload, dict) or set(payload) - {"remote_base_url", "management_key"}:
                self._json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return None
            if "remote_base_url" not in payload or not isinstance(payload["remote_base_url"], str):
                self._json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return None
            if "management_key" in payload and not isinstance(payload["management_key"], str):
                self._json({"error": "invalid_request"}, HTTPStatus.BAD_REQUEST)
                return None
            return payload

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json({"status": "ok", "schema_version": 1})
            elif self.path == "/api/v1/summary":
                self._json(service.get_summary())
            elif self.path == "/api/v1/settings":
                self._json(service.settings())
            else:
                self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path == "/api/v1/refresh":
                accepted = service.request_refresh()
                self._json({"status": "scheduled" if accepted else "debounced", "schema_version": 1}, HTTPStatus.ACCEPTED)
                return
            if self.path != "/api/v1/settings":
                self._json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
                return
            payload = self._config_request()
            if payload is None:
                return
            try:
                config = service.update_source_config(
                    payload["remote_base_url"],
                    payload.get("management_key"),
                )
            except ValueError:
                # The request body can include a management key; never echo its value.
                self._json({"error": "invalid_config"}, HTTPStatus.BAD_REQUEST)
                return
            self._json({"status": "scheduled", **config}, HTTPStatus.ACCEPTED)

    return Handler


def serve(service: SummaryService) -> None:
    config = service.config
    if config.bind_host != "127.0.0.1":
        raise ValueError("refusing non-local bind")
    ThreadingHTTPServer((config.bind_host, config.bind_port), handler_for(service)).serve_forever()
