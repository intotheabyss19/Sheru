"""Volume, media, timers, clipboard — all via AppleScript / shell, no AI."""
from __future__ import annotations

import subprocess
import threading
import time

_TIMERS: list[threading.Timer] = []


def _osa(script: str) -> str:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10).stdout.strip()


def set_volume(percent: int) -> str:
    percent = max(0, min(100, int(percent)))
    _osa(f"set volume output volume {percent}")
    return f"Volume {percent} percent."


def change_volume(delta: int) -> str:
    cur = int(_osa("output volume of (get volume settings)") or 50)
    return set_volume(cur + delta)


def mute(state: bool = True) -> str:
    _osa(f"set volume output muted {'true' if state else 'false'}")
    return "Muted." if state else "Unmuted."


def media(cmd: str) -> str:
    """cmd in play|pause|next|previous — targets Spotify if running, else Music."""
    app = "Spotify" if _osa('tell application "System Events" to (name of processes) contains "Spotify"') == "true" else "Music"
    verb = {"play": "play", "pause": "pause", "next": "next track", "previous": "previous track"}[cmd]
    _osa(f'tell application "{app}" to {verb}')
    return f"{cmd.capitalize()} on {app}."


def clipboard() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def set_timer(seconds: int, on_fire, label: str = "timer") -> str:
    t = threading.Timer(seconds, on_fire, args=(f"Your {label} is done.",))
    t.daemon = True
    t.start()
    _TIMERS.append(t)
    m, s = divmod(int(seconds), 60)
    human = f"{m} minute{'s' if m != 1 else ''}" if m else ""
    human += (f" {s} seconds" if s and m else f"{s} seconds" if s else "")
    return f"Timer set for {human.strip()}."


def now() -> str:
    return time.strftime("It's %I:%M %p on %A, %B %d.").replace(" 0", " ")
