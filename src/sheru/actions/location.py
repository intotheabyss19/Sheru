"""Resolve the user's rough location so 'weather at my location' becomes 'weather in Ravangla'.

Uses IP-based geolocation (approximate, city-level). Cached to data/ (gitignored). Degrades to no-op
if offline — the query is passed through unchanged.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request

from .. import config

_CACHE = config.DATA_DIR / "location.json"
_lock = threading.Lock()
_mem: dict | None = None
_PHRASE = re.compile(r"\b(my current location|my location|my area|around me|near me|nearby|over here|here)\b", re.I)


def where(max_age: float = 3600) -> dict:
    global _mem
    with _lock:
        if _mem and time.time() - _mem.get("_ts", 0) < max_age:
            return _mem
        try:
            d = json.loads(_CACHE.read_text())
            if time.time() - d.get("_ts", 0) < max_age:
                _mem = d
                return d
        except Exception:
            pass
        try:
            url = "http://ip-api.com/json/?fields=city,regionName,country,lat,lon"
            with urllib.request.urlopen(url, timeout=4) as r:
                d = json.loads(r.read().decode())
            d["_ts"] = time.time()
            _mem = d
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            _CACHE.write_text(json.dumps(d))
            return d
        except Exception:
            return _mem or {}


def describe() -> str:
    # authoritative user-set location (profile) wins over unreliable IP geolocation
    prof = config._profile().get("location") if hasattr(config, "_profile") else None
    if prof:
        return prof
    d = where()
    parts = [d.get("city"), d.get("regionName")]
    return ", ".join(p for p in parts if p)


def localize(text: str) -> str:
    """Replace 'my location'/'here'/'near me' with the resolved city, if known."""
    city = describe()
    return _PHRASE.sub(city, text) if city else text


def mentions_here(text: str) -> bool:
    return bool(_PHRASE.search(text))
