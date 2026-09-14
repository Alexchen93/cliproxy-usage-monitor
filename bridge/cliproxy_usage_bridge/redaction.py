"""Keep secrets out of API responses and logs."""
from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = re.compile(r"(?:authorization|token|secret|password|cookie|(?:api|access|management)[_-]?key)", re.I)
_BEARER = re.compile(r"\bBearer\s+[^\s,;]+", re.I)
_JWT = re.compile(r"\beyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")


def redact(value: Any) -> Any:
    """Recursively redact known credentials from an untrusted error/payload."""
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if _SECRET_KEYS.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _JWT.sub("[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value))
    return value


def safe_error(error: object) -> str:
    return str(redact(str(error)))[:500]
