"""Global hotkey via pyobjc NSEvent monitors (needs Accessibility). No Carbon/ctypes.

Registers BOTH a global monitor (fires when other apps are focused) AND a local monitor (fires when Sheru's
own panel is focused) — a global monitor alone misses key presses while Sheru is frontmost. Default key F18
(pair with hidutil F5->F18 remap).
"""
from __future__ import annotations

KEY_F18 = 79
KEY_F5 = 96
_monitors: list = []


def register(on_press, key_code: int = KEY_F18) -> bool:
    try:
        from AppKit import NSEvent, NSEventMaskKeyDown
    except Exception:
        return False

    def _global(event):
        try:
            if event.keyCode() == key_code:
                on_press()
        except Exception:
            pass

    def _local(event):
        try:
            if event.keyCode() == key_code:
                on_press()
        except Exception:
            pass
        return event      # pass the event through (don't swallow)

    g = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, _global)
    l = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSEventMaskKeyDown, _local)
    _monitors.extend([g, l])
    return g is not None or l is not None
