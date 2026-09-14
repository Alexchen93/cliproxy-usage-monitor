from __future__ import annotations

import json
from typing import Any

from ..cliproxy_client import ManagementClient, ManagementError
from ..models import clamp_percent, window_schema
from ..redaction import safe_error

_WHAM_URL = "https://chatgpt.com/backend-api/wham/usage"
_WHAM_HEADERS = {"Authorization": "Bearer $TOKEN$", "Content-Type": "application/json", "User-Agent": "codex_cli_rs/0.76.0"}


def _entry_provider(entry: dict[str, Any]) -> str:
    return str(entry.get("provider", entry.get("type", ""))).lower()


def _window(rate_limit: dict[str, Any], seconds: int, fallback: str) -> dict[str, Any] | None:
    candidates = [rate_limit.get("primary_window", rate_limit.get("primaryWindow")), rate_limit.get("secondary_window", rate_limit.get("secondaryWindow"))]
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("limit_window_seconds", candidate.get("limitWindowSeconds")) == seconds:
            return candidate
    candidate = rate_limit.get(fallback)
    return candidate if isinstance(candidate, dict) else None


def parse_usage(payload: dict[str, Any]) -> dict[str, Any]:
    rate = payload.get("rate_limit", payload.get("rateLimit", {}))
    if not isinstance(rate, dict):
        return {}
    result: dict[str, Any] = {}
    for name, seconds, fallback in (("five_hour", 5 * 3600, "primary_window"), ("weekly", 7 * 86400, "secondary_window")):
        item = _window(rate, seconds, fallback)
        if isinstance(item, dict):
            parsed = window_schema(item)
            if parsed:
                result[name] = parsed
    return result


def _account_id(entry: dict[str, Any]) -> str:
    keys = ("chatgpt_account_id", "chatgptAccountId", "account_id", "accountId")
    for source in (entry, entry.get("id_token"), entry.get("idToken")):
        if not isinstance(source, dict):
            continue
        for key in keys:
            if isinstance(source.get(key), str) and source[key]:
                return source[key]
    return ""


def _account_label(entry: dict[str, Any], position: int) -> str:
    for key in ("email", "label", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return f"Account {position}"


def _warning_level(values: list[int]) -> str:
    return "critical" if any(value >= 95 for value in values) else "warning" if any(value >= 80 for value in values) else "normal"


def collect(client: ManagementClient) -> tuple[dict[str, Any] | None, list[dict[str, str]], bool]:
    """Read metadata from /auth-files and live quota only through /api-call."""
    errors: list[dict[str, str]] = []
    try:
        entries = [entry for entry in client.auth_files() if _entry_provider(entry) == "codex"]
    except ManagementError as exc:
        # An HTTP status proves the proxy answered even when authentication or
        # an individual management route failed. Network failures have no
        # status and therefore mark the proxy offline.
        return None, [{"provider": "codex", "message": safe_error(exc)}], exc.status is not None
    accounts: list[dict[str, Any]] = []
    available = 0
    for position, entry in enumerate(entries, 1):
        auth_index = str(entry.get("auth_index", entry.get("authIndex", "")))
        account_id = _account_id(entry)
        account: dict[str, Any] = {
            "display_name": _account_label(entry, position),
            "available": False,
            "summary_used_percent": None,
            "warning_level": "normal",
            "windows": {},
        }
        if not auth_index or not account_id:
            errors.append({"provider": "codex", "message": "account metadata missing auth_index or chatgpt_account_id"})
            account["error"] = "Account metadata is incomplete"
            accounts.append(account)
            continue
        try:
            response = client.api_call(auth_index, _WHAM_URL, {**_WHAM_HEADERS, "Chatgpt-Account-Id": account_id})
            status = response.get("status_code", response.get("statusCode"))
            body = response.get("body")
            if isinstance(body, str):
                body = json.loads(body)
            if status != 200 or not isinstance(body, dict):
                raise ManagementError(f"quota request returned HTTP {status}", int(status) if isinstance(status, int) else None)
            parsed = parse_usage(body)
            if not parsed:
                raise ManagementError("quota response had no usable rate-limit windows")
            used = [window["used_percent"] for window in parsed.values()]
            account.update({
                "available": True,
                "summary_used_percent": max(used) if used else None,
                "warning_level": _warning_level(used),
                "windows": parsed,
            })
            available += 1
        except (ManagementError, ValueError, json.JSONDecodeError) as exc:
            errors.append({"provider": "codex", "message": safe_error(exc)})
            account["error"] = safe_error(exc)
            accounts.append(account)
            if isinstance(exc, ManagementError) and exc.status == 401:
                break
            continue
        accounts.append(account)
    if not entries:
        return None, errors, True
    aggregate: dict[str, Any] = {}
    for name in ("five_hour", "weekly"):
        candidates = [account["windows"][name] for account in accounts if name in account["windows"]]
        if candidates:
            # The panel summary shows the pool's highest-used member, while the
            # popup preserves every account's own windows below.
            aggregate[name] = max(candidates, key=lambda item: item["used_percent"])
    used = [item["used_percent"] for item in aggregate.values()]
    return {
        "display_name": "Codex", "summary_used_percent": max(used) if used else None,
        "warning_level": _warning_level(used),
        "estimated": False, "accounts_total": len(entries), "accounts_available": available,
        "accounts": accounts, "windows": aggregate,
    }, errors, True
