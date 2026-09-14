from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import stat
import tomllib


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


def load_config(path: str | Path) -> Config:
    path = Path(path).expanduser()
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ValueError(f"refusing insecure config permissions {oct(mode)}; require 0600")
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    remote = str(data.get("remote_base_url", "")).rstrip("/")
    key = str(data.get("management_key", ""))
    if not remote.startswith(("http://", "https://")) or not key:
        raise ValueError("remote_base_url and management_key are required")
    host = str(data.get("bind_host", "127.0.0.1"))
    if host != "127.0.0.1":
        raise ValueError("bridge must bind exactly to 127.0.0.1")
    return Config(
        remote_base_url=remote, management_key=key, bind_host=host,
        bind_port=int(data.get("bind_port", 17831)),
        timeout_seconds=float(data.get("timeout_seconds", 8)),
        cache_ttl_seconds=int(data.get("cache_ttl_seconds", 30)),
        stale_after_seconds=int(data.get("stale_after_seconds", 300)),
        refresh_debounce_seconds=int(data.get("refresh_debounce_seconds", 10)),
    )
