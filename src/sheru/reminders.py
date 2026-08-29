"""Reminders: parse a natural time, schedule a spoken/notified reminder, persist across restarts."""
from __future__ import annotations

import datetime
import json
import re
import threading
import time
from pathlib import Path

from . import config

STORE = Path(config.DATA_DIR) / "reminders.jsonl"
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10,
          "fifteen": 15, "twenty": 20, "thirty": 30, "half": 0.5, "couple": 2, "few": 3}


def parse_when(text: str):
    """Return (seconds_from_now, human_label) or (None, None) if no time found."""
    t = text.strip().lower()
    m = re.search(r"\bin\s+(\d+|" + "|".join(_WORDS) + r")\s*(second|sec|minute|min|hour|hr)s?\b", t)
    if m:
        n = _WORDS.get(m.group(1), None)
        n = float(m.group(1)) if n is None else n
        unit = m.group(2)
        mult = 1 if unit.startswith("sec") else 60 if unit.startswith("min") else 3600
        return n * mult, f"in {m.group(1)} {unit}{'s' if n != 1 else ''}"
    _H = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,
          "ten":10,"eleven":11,"twelve":12,"noon":12,"midnight":0}
    mw = re.search(r"\bat\s+(" + "|".join(_H) + r")\s*(a\.?m\.?|p\.?m\.?)?\b", t)
    if mw:
        t = t.replace(mw.group(0), f"at {_H[mw.group(1)]}{' '+mw.group(2) if mw.group(2) else ''}", 1)
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b", t)
    if m:
        h, mn = int(m.group(1)), int(m.group(2) or 0)
        ap = (m.group(3) or "").replace(".", "")
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        now = datetime.datetime.now()
        target = now.replace(hour=h % 24, minute=mn, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return (target - now).total_seconds(), f"at {h % 24 or 12}:{mn:02d}"
    return None, None


def _persist(task, fire_ts):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE, "a") as f:
        f.write(json.dumps({"task": task, "fire_ts": round(fire_ts, 1)}) + "\n")


def schedule(task: str, seconds: float, on_fire, persist: bool = True) -> None:
    if persist:
        _persist(task, time.time() + seconds)
    from . import alarms
    alarms.schedule(task, seconds, on_fire, spoken=f"Reminder: {task}.")     # rings a bell + shows in the menu bar


def restore(on_fire) -> int:
    """Reschedule still-pending reminders after a restart; drop past-due. Returns count restored."""
    if not STORE.exists():
        return 0
    now = time.time()
    kept = []
    for line in STORE.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("fire_ts", 0) > now + 1:
            kept.append(r)
            schedule(r["task"], r["fire_ts"] - now, on_fire, persist=False)
    STORE.write_text("\n".join(json.dumps(r) for r in kept) + ("\n" if kept else ""))
    return len(kept)
