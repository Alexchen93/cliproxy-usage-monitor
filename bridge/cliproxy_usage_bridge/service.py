from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import threading
import time
from typing import Any

from .cliproxy_client import ManagementClient
from .config import Config, rewrite_source_config
from .providers.codex import collect as collect_codex
from .redaction import safe_error


class SummaryService:
    def __init__(
        self,
        config: Config,
        client: ManagementClient | None = None,
        *,
        start_refresh: bool = True,
        client_factory: Callable[[Config], ManagementClient] = ManagementClient,
    ) -> None:
        self.config = config
        self._client_factory = client_factory
        self.client = client or client_factory(config)
        self._lock = threading.Lock()
        self._summary: dict[str, Any] | None = None
        self._updated_monotonic = 0.0
        self._refresh_started = 0.0
        self._refresh_in_progress = False
        self._generation = 0
        if start_refresh:
            with self._lock:
                self._start_refresh_locked()

    def settings(self) -> dict[str, object]:
        """Return the exact nonsecret settings contract for the local UI."""
        with self._lock:
            return self.settings_locked()

    def update_source_config(self, remote_base_url: object, management_key: object | None = None) -> dict[str, object]:
        """Persist a source update, discard state tied to the old credential, and refresh."""
        with self._lock:
            config = rewrite_source_config(
                self.config,
                remote_base_url,
                None if management_key in (None, "") else management_key,
            )
            self._generation += 1
            self.config = config
            self.client = self._client_factory(config)
            self._summary = None
            self._updated_monotonic = 0.0
            self._refresh_started = 0.0
            self._refresh_in_progress = False
            self._start_refresh_locked()
            return self.settings_locked()

    def settings_locked(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "remote_base_url": self.config.remote_base_url,
            "management_key_configured": bool(self.config.management_key),
        }

    def _age(self) -> int:
        return max(0, round(time.monotonic() - self._updated_monotonic)) if self._updated_monotonic else 0

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            result = self._empty_summary_locked() if self._summary is None else self._decorate_cache_locked()
            if (
                not self.client.auth_blocked
                and not self._refresh_in_progress
                and (self._summary is None or self._age() > self.config.cache_ttl_seconds)
            ):
                self._start_refresh_locked()
            return result

    def request_refresh(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if (
                self.client.auth_blocked
                or self._refresh_in_progress
                or now - self._refresh_started < self.config.refresh_debounce_seconds
            ):
                return False
            self._start_refresh_locked()
            return True

    def _start_refresh_locked(self) -> None:
        if self._refresh_in_progress:
            return
        self._refresh_started = time.monotonic()
        self._refresh_in_progress = True
        threading.Thread(
            target=self.refresh,
            args=(self.client, self._generation),
            daemon=True,
            name="quota-refresh",
        ).start()

    def refresh(self, client: ManagementClient | None = None, generation: int | None = None) -> None:
        # Provider I/O must never hold the cache lock: the GNOME popup should
        # always receive the current cache immediately during a slow refresh.
        client = client or self.client
        generation = self._generation if generation is None else generation
        started = time.monotonic()
        try:
            provider, errors, online = collect_codex(client)
        except Exception as exc:  # Keep the daemon alive on malformed upstream data.
            provider = None
            errors = [{"provider": "codex", "message": safe_error(exc)}]
            online = False
        latency = round((time.monotonic() - started) * 1000)
        now = time.monotonic()

        with self._lock:
            if generation != self._generation:
                return
            old_providers = dict((self._summary or {}).get("providers", {}))
            if provider:
                old_providers["codex"] = provider
                self._updated_monotonic = now
            has_data = bool(old_providers)
            status = "ok" if provider and not errors else "partial" if has_data else "error"
            updated_at = (
                datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
                if provider
                else (self._summary or {}).get("updated_at")
            )
            self._summary = {
                "schema_version": 1,
                "status": status,
                "updated_at": updated_at,
                "data_age_seconds": 0,
                "cache_state": "live" if provider else "stale",
                "proxy": {
                    "online": online,
                    "latency_ms": latency,
                    "auth_status": "error" if client.auth_blocked else "ok",
                },
                "providers": old_providers,
                "errors": errors,
            }
            self._refresh_in_progress = False

    def _decorate_cache_locked(self) -> dict[str, Any]:
        assert self._summary is not None
        result = dict(self._summary)
        age = self._age()
        result["data_age_seconds"] = age
        if not result.get("providers"):
            result["cache_state"] = "stale"
        elif age <= self.config.cache_ttl_seconds:
            result["cache_state"] = "live"
        elif age <= self.config.stale_after_seconds:
            result["cache_state"] = "cached"
        else:
            result["cache_state"] = "stale"
        return result

    def _empty_summary_locked(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "status": "error",
            "updated_at": None,
            "data_age_seconds": 0,
            "cache_state": "stale",
            "proxy": {"online": False, "latency_ms": None, "auth_status": "unknown"},
            "providers": {},
            "errors": [{"provider": "bridge", "message": "initial refresh in progress"}],
        }
