"""Cheap, cached reachability check so the router can prefer Claude Code when online and fall back when not."""
from __future__ import annotations

import socket
import time

_cache = {"t": 0.0, "v": False}


def online(host: str = "api.anthropic.com", port: int = 443, timeout: float = 1.5, ttl: float = 15.0) -> bool:
    """True if a TCP path to `host:port` exists. Cached for `ttl` seconds. (A TLS-intercepting proxy still
    reports reachable — actual `claude -p` failures are caught separately and trigger the local fallback.)"""
    now = time.monotonic()
    if now - _cache["t"] < ttl:
        return _cache["v"]
    try:
        socket.create_connection((host, port), timeout).close()
        v = True
    except OSError:
        v = False
    _cache.update(t=now, v=v)
    return v
