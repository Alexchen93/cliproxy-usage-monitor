from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Config
from .redaction import safe_error


class ManagementError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class ManagementClient:
    config: Config
    opener: Any = urlopen
    auth_blocked: bool = False

    def _request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        if self.auth_blocked:
            raise ManagementError("management authentication is blocked after HTTP 401", 401)
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            self.config.remote_base_url + "/v0/management" + path,
            data=data, method=method,
            headers={"Authorization": "Bearer " + self.config.management_key, "Accept": "application/json", **({"Content-Type": "application/json"} if data else {})},
        )
        try:
            with self.opener(request, timeout=self.config.timeout_seconds) as response:
                raw = response.read()
                return json.loads(raw.decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 401:
                self.auth_blocked = True
            raise ManagementError(f"management API HTTP {exc.code}", exc.code) from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ManagementError(safe_error(exc)) from exc

    def auth_files(self) -> list[dict[str, Any]]:
        payload = self._request("/auth-files")
        files = payload.get("files", []) if isinstance(payload, dict) else []
        return [item for item in files if isinstance(item, dict)]

    def api_call(self, auth_index: str, url: str, headers: dict[str, str]) -> dict[str, Any]:
        payload = {"auth_index": auth_index, "method": "GET", "url": url, "header": headers}
        response = self._request("/api-call", "POST", payload)
        if not isinstance(response, dict):
            raise ManagementError("invalid api-call response")
        return response

    def probe_latency_ms(self) -> int:
        start = time.monotonic()
        self.auth_files()
        return round((time.monotonic() - start) * 1000)
