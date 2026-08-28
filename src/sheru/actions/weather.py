"""Silent weather fetch via wttr.in — no browser window, no API key, no Claude dependency.

Sheru used to hand weather to Claude Code, which is unreliable (subscription/org can disable `claude -p`).
This answers directly and speaks the result, Siri-style. Returns None on any failure so the caller can
fall back to Claude.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request


def fetch(city: str) -> str | None:
    url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=7) as r:
            d = json.load(r)
        cur = d["current_condition"][0]
        desc = cur["weatherDesc"][0]["value"].strip().lower()
        temp = cur["temp_C"]
        feels = cur["FeelsLikeC"]
        area = (d.get("nearest_area") or [{}])[0]
        place = ((area.get("areaName") or [{}])[0].get("value") or city).strip()
        tail = f", feels like {feels}" if feels and feels != temp else ""
        return f"It's {temp} degrees in {place} right now, {desc}{tail}."
    except Exception:
        return None
