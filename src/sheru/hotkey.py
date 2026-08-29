"""Global hotkey via pyobjc NSEvent monitors (needs Accessibility). No Carbon/ctypes.

Registers BOTH a global monitor (fires when other apps are focused) AND a local monitor (fires when Sheru's
own panel is focused) — a global monitor alone misses key presses while Sheru is frontmost. Default key F18
(pair with hidutil F5->F18 remap).
"""
from __future__ import annotations

import time

KEY_F18 = 79
KEY_F5 = 96
_monitors: list = []


def register(on_tap, on_hold=None, key_code: int = KEY_F18, hold_threshold: float = 0.4) -> bool:
    """Fire on_tap for a quick press and on_hold for a press held >= hold_threshold seconds (decided on release).
    Monitors key-down (to timestamp the press, ignoring auto-repeat) AND key-up. If on_hold is None it behaves
    like a plain press trigger. Needs Accessibility; global monitor fires for other apps, local for Sheru's panel."""
    try:
        from AppKit import NSEvent, NSEventMaskKeyDown, NSEventMaskKeyUp
    except Exception:
        return False

    state = {"down": None}

    def _down(event):
        try:
            if event.keyCode() == key_code and not event.isARepeat() and state["down"] is None:
                state["down"] = time.monotonic()          # first press only; ignore held-key auto-repeat
        except Exception:
            pass

    def _up(event):
        try:
            if event.keyCode() == key_code and state["down"] is not None:
                held = time.monotonic() - state["down"]
                state["down"] = None
                (on_hold if (on_hold is not None and held >= hold_threshold) else on_tap)()
        except Exception:
            pass

    def _down_local(event):
        _down(event); return event                        # pass through (don't swallow)

    def _up_local(event):
        _up(event); return event

    ms = [
        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, _down),
        NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyUp, _up),
        NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, _down_local),
        NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyUp, _up_local),
    ]
    _monitors.extend(ms)
    return any(m is not None for m in ms)
