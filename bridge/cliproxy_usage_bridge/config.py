from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import stat
import tempfile
import tomllib
from urllib.parse import urlsplit


_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_ASSIGNMENT = re.compile(r"^(?P<prefix>\s*{name}\s*=\s*).*$", re.MULTILINE)


@dataclass(frozen=True)
class Config:
    remote_base_url: str
    management_key: str
    bind_host: str = "127.0.0.1"
    bind_port: int = 17831
    timeout_seconds: float = 8.0
    cache_ttl_seconds: int = 30
    stale_after_seconds: int = 300
    refresh_debounce_seconds: int = 10
    config_path: Path | None = None


def _validate_remote_base_url(value: object) -> str:
    remote = str(value).rstrip("/")
    parsed = urlsplit(remote)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("remote_base_url must be an http(s) private/local address")

    host = parsed.hostname
    if host != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise ValueError("remote_base_url must use a literal private/local address") from exc
        if not (address.is_private or address.is_loopback or address.is_link_local or address in _CGNAT):
            raise ValueError("remote_base_url must use a private/local address")
    return remote


def _validate_management_key(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\r" in value or "\n" in value:
        raise ValueError("management_key must be a non-empty single-line string")
    return value


def _read_config(path: Path) -> dict[str, object]:
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        raise ValueError(f"refusing insecure config permissions {oct(mode)}; require 0600")
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _config_from_data(data: dict[str, object], path: Path) -> Config:
    remote = _validate_remote_base_url(data.get("remote_base_url", ""))
    key = _validate_management_key(data.get("management_key", ""))
    host = str(data.get("bind_host", "127.0.0.1"))
    if host != "127.0.0.1":
        raise ValueError("bridge must bind exactly to 127.0.0.1")
    return Config(
        remote_base_url=remote,
        management_key=key,
        bind_host=host,
        bind_port=int(data.get("bind_port", 17831)),
        timeout_seconds=float(data.get("timeout_seconds", 8)),
        cache_ttl_seconds=int(data.get("cache_ttl_seconds", 30)),
        stale_after_seconds=int(data.get("stale_after_seconds", 300)),
        refresh_debounce_seconds=int(data.get("refresh_debounce_seconds", 10)),
        config_path=path,
    )


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser()
    return _config_from_data(_read_config(path), path)


def _replace_assignment(text: str, name: str, value: str) -> str:
    pattern = re.compile(_ASSIGNMENT.pattern.format(name=re.escape(name)), re.MULTILINE)
    replacement = f"{name} = {json.dumps(value, ensure_ascii=True)}"
    updated, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise ValueError(f"config is missing {name}")
    return updated


def rewrite_source_config(
    config: Config,
    remote_base_url: object,
    management_key: object | None = None,
) -> Config:
    """Atomically replace editable source settings while retaining all other TOML."""
    if config.config_path is None:
        raise ValueError("source config path is unavailable")
    remote = _validate_remote_base_url(remote_base_url)
    key = None if management_key is None else _validate_management_key(management_key)
    path = config.config_path
    data = _read_config(path)
    # Refuse to rewrite an invalid file, including one that was swapped after startup.
    _config_from_data(data, path)
    text = path.read_text(encoding="utf-8")
    text = _replace_assignment(text, "remote_base_url", remote)
    if key is not None:
        text = _replace_assignment(text, "management_key", key)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as stream:
        temporary_path = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            stream.close()
            temporary_path.chmod(0o600)
            temporary_path.replace(path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
    return load_config(path)
