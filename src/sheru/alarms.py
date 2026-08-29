"""Alarms / timers / reminders with a REAL bell + a live registry (for the menu bar).

One backend behind system.set_timer, reminders, and 'set an alarm'. When one fires it RINGS — loops a bell
sound until dismissed by voice ('stop'/'dismiss'), the menu bar, or a 45s cap — and speaks its announcement.
The menu-bar refresh hook (set_on_change) is called on every change; it must marshal to the main thread itself.
"""
from __future__ import annotations

import itertools
import subprocess
import threading
import time

BELL = "/System/Library/Sounds/Glass.aiff"      # always present on macOS; looped as the alarm bell
_ids = itertools.count(1)
_alarms: dict[int, dict] = {}                    # id -> {label, spoken, fire_ts, timer}
_lock = threading.Lock()
_ring_stop = threading.Event()
_ringing = threading.Event()
_on_change = [lambda: None]                      # menu-bar refresh hook


def set_on_change(cb) -> None:
    _on_change[0] = cb or (lambda: None)


def _changed() -> None:
    try:
        _on_change[0]()
    except Exception:
        pass


def active() -> list[dict]:
    """Pending alarms, soonest first — for the menu bar."""
    now = time.time()
    with _lock:
        items = [{"id": i, "label": a["label"], "fire_ts": a["fire_ts"], "remaining": max(0.0, a["fire_ts"] - now)}
                 for i, a in _alarms.items()]
    return sorted(items, key=lambda a: a["fire_ts"])


def cancel(aid: int) -> bool:
    with _lock:
        a = _alarms.pop(aid, None)
    if a:
        a["timer"].cancel()
        _changed()
        return True
    return False


def cancel_all() -> int:
    with _lock:
        items = list(_alarms.values())
        _alarms.clear()
    for a in items:
        a["timer"].cancel()
    if items:
        _changed()
    return len(items)


def schedule(label: str, seconds: float, on_fire, spoken: str | None = None) -> int:
    """Ring + announce `spoken` after `seconds`. `label` shows in the menu bar. Returns the alarm id."""
    aid = next(_ids)
    say = spoken or f"{label}."

    def _fire():
        with _lock:
            _alarms.pop(aid, None)
        _changed()
        ring()
        try:
            on_fire(say)
        except Exception:
            pass

    t = threading.Timer(max(1.0, seconds), _fire)
    t.daemon = True
    with _lock:
        _alarms[aid] = {"label": label, "spoken": say, "fire_ts": time.time() + seconds, "timer": t}
    t.start()
    _changed()
    return aid


def ring(max_seconds: float = 45.0) -> None:
    """Start looping the bell until stop_ring() or max_seconds. No-op if already ringing."""
    if _ringing.is_set():
        return
    _ring_stop.clear()
    _ringing.set()
    _changed()

    def _loop():
        t0 = time.monotonic()
        try:
            while not _ring_stop.is_set() and time.monotonic() - t0 < max_seconds:
                try:
                    p = subprocess.Popen(["afplay", BELL])
                except Exception:
                    break
                while p.poll() is None:
                    if _ring_stop.is_set():
                        p.terminate()
                        break
                    time.sleep(0.1)
        finally:
            _ringing.clear()
            _changed()

    threading.Thread(target=_loop, name="sheru-alarm-ring", daemon=True).start()


def stop_ring() -> bool:
    """Silence a ringing alarm. Returns True if one was actually ringing."""
    if _ringing.is_set():
        _ring_stop.set()
        return True
    return False


def is_ringing() -> bool:
    return _ringing.is_set()


def human_remaining(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m" + (f" {s}s" if s else "")
    h, m = divmod(m, 60)
    return f"{h}h" + (f" {m}m" if m else "")
