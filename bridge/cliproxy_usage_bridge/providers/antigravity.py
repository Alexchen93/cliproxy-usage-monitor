from __future__ import annotations

import json
from typing import Any

from ..cliproxy_client import ManagementClient, ManagementError
from ..models import clamp_percent
from ..redaction import safe_error

_QUOTA_URLS = (
    "https://daily-cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
    "https://daily-cloudcode-pa.sandbox.googleapis.com/v1internal:fetchAvailableModels",
    "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
)
_QUOTA_HEADERS = {
    "Authorization": "Bearer $TOKEN$",
    "Content-Type": "application/json",
    "User-Agent": "antigravity/1.11.5 windows/amd64",
}


def _entry_provider(entry: dict[str, Any]) -> str:
    return str(entry.get("provider", entry.get("type", ""))).lower()


def _account_label(entry: dict[str, Any], position: int) -> str:
    for key in ("email", "label", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return f"Account {position}"


def _warning_level(values: list[int]) -> str:
    return "critical" if any(value >= 95 for value in values) else "warning" if any(value >= 80 for value in values) else "normal"


def parse_models(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize the model quota response without exposing OAuth metadata."""
    raw_models = payload.get("models")
    if not isinstance(raw_models, dict):
        return {}
    parsed: list[tuple[str, dict[str, Any]]] = []
    for model_id, model in raw_models.items():
        if not isinstance(model_id, str) or not isinstance(model, dict):
            continue
        quota = model.get("quotaInfo")
        if not isinstance(quota, dict) or not isinstance(quota.get("remainingFraction"), (int, float)):
            continue
        remaining = clamp_percent(float(quota["remainingFraction"]) * 100)
        if remaining is None:
            continue
        window: dict[str, Any] = {
            "used_percent": 100 - remaining,
            "remaining_percent": remaining,
            "label": str(model.get("displayName") or model_id)[:80],
        }
        reset = quota.get("resetTime")
        if isinstance(reset, str) and reset:
            window["reset_at"] = reset
        parsed.append((model_id, window))
    # Display the most constrained pools first, which keeps the popup useful
    # even when Antigravity exposes many model-specific quota buckets.
    parsed.sort(key=lambda item: (-item[1]["used_percent"], item[1]["label"].lower()))
    return dict(parsed)


def _quota_response(client: ManagementClient, auth_index: str) -> dict[str, Any]:
    last_error: ManagementError | None = None
    for url in _QUOTA_URLS:
        try:
            response = client.api_call(auth_index, url, _QUOTA_HEADERS, "{}")
            status = response.get("status_code", response.get("statusCode"))
            body = response.get("body")
            if isinstance(body, str):
                body = json.loads(body)
            if status == 200 and isinstance(body, dict):
                return body
            last_error = ManagementError(f"quota request returned HTTP {status}", int(status) if isinstance(status, int) else None)
        except (ManagementError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc if isinstance(exc, ManagementError) else ManagementError(str(exc))
    raise last_error or ManagementError("quota request failed")


def collect(client: ManagementClient) -> tuple[dict[str, Any] | None, list[dict[str, str]], bool]:
    errors: list[dict[str, str]] = []
    try:
        entries = [entry for entry in client.auth_files() if _entry_provider(entry) == "antigravity"]
    except ManagementError as exc:
        return None, [{"provider": "antigravity", "message": safe_error(exc)}], exc.status is not None

    accounts: list[dict[str, Any]] = []
    available = 0
    for position, entry in enumerate(entries, 1):
        auth_index = str(entry.get("auth_index", entry.get("authIndex", "")))
        account: dict[str, Any] = {
            "display_name": _account_label(entry, position),
            "available": False,
            "summary_used_percent": None,
            "warning_level": "normal",
            "windows": {},
        }
        if not auth_index:
            account["error"] = "Account metadata is incomplete"
            errors.append({"provider": "antigravity", "message": "account metadata missing auth_index"})
            accounts.append(account)
            continue
        try:
            windows = parse_models(_quota_response(client, auth_index))
            if not windows:
                raise ManagementError("quota response had no usable model quotas")
            used = [window["used_percent"] for window in windows.values()]
            account.update({
                "available": True,
                "summary_used_percent": max(used),
                "warning_level": _warning_level(used),
                "windows": windows,
            })
            available += 1
        except ManagementError as exc:
            account["error"] = safe_error(exc)
            errors.append({"provider": "antigravity", "message": safe_error(exc)})
        accounts.append(account)

    if not entries:
        return None, errors, True
    aggregate: dict[str, dict[str, Any]] = {}
    for account in accounts:
        for name, window in account["windows"].items():
            current = aggregate.get(name)
            if current is None or window["used_percent"] > current["used_percent"]:
                aggregate[name] = window
    used = [window["used_percent"] for window in aggregate.values()]
    return {
        "display_name": "Antigravity",
        "summary_used_percent": max(used) if used else None,
        "warning_level": _warning_level(used),
        "estimated": False,
        "accounts_total": len(entries),
        "accounts_available": available,
        "accounts": accounts,
        "windows": aggregate,
    }, errors, True
