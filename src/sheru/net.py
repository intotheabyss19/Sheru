"""Cheap, cached reachability check so the router can prefer Claude Code when online and fall back when not."""
from __future__ import annotations

import socket
import time

_cache: dict[tuple[str, int], tuple[float, bool]] = {}   # per-host: one host being up says nothing about another


def online(host: str = "api.anthropic.com", port: int = 443, timeout: float = 1.5, ttl: float = 15.0) -> bool:
    """True if a TCP path to `host:port` exists. Cached for `ttl` seconds, per host. (A TLS-intercepting proxy
    still reports reachable — actual `claude -p` failures are caught separately and trigger the local fallback.)"""
    now = time.monotonic()
    hit = _cache.get((host, port))
    if hit and now - hit[0] < ttl:
        return hit[1]
    try:
        socket.create_connection((host, port), timeout).close()
        v = True
    except OSError:
        v = False
    _cache[(host, port)] = (now, v)
    return v
