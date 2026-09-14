from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def clamp_percent(value: object) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return max(0, min(100, round(float(value))))


def iso_reset(window: dict[str, Any]) -> str | None:
    reset = window.get("reset_at", window.get("resetAt"))
    if isinstance(reset, (int, float)):
        return datetime.fromtimestamp(reset).astimezone().isoformat(timespec="seconds")
    if isinstance(reset, str) and reset:
        return reset
    seconds = window.get("reset_after_seconds", window.get("resetAfterSeconds"))
    if isinstance(seconds, (int, float)) and seconds >= 0:
        return (datetime.now().astimezone() + timedelta(seconds=seconds)).replace(microsecond=0).isoformat()
    return None


def window_schema(window: dict[str, Any]) -> dict[str, Any] | None:
    used = clamp_percent(window.get("used_percent", window.get("usedPercent")))
    if used is None:
        return None
    result = {"used_percent": used, "remaining_percent": 100 - used}
    reset = iso_reset(window)
    if reset:
        result["reset_at"] = reset
    return result


def summary_schema(summary: dict[str, Any]) -> bool:
    """Small strict boundary validator for the public v1 response."""
    required = {"schema_version", "status", "updated_at", "data_age_seconds", "cache_state", "proxy", "providers", "errors"}
    if not required.issubset(summary) or summary["schema_version"] != 1:
        return False
    if summary["status"] not in {"ok", "partial", "error"}:
        return False
    if summary["cache_state"] not in {"live", "cached", "stale"}:
        return False
    return isinstance(summary["proxy"], dict) and isinstance(summary["providers"], dict) and isinstance(summary["errors"], list)
