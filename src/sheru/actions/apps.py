"""Open / quit / switch macOS applications by fuzzy name."""
from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path

from rapidfuzz import process, fuzz

APP_DIRS = (Path("/Applications"), Path("/System/Applications"), Path("/System/Applications/Utilities"),
            Path.home() / "Applications")
ALIASES = {
    "zen browser": "Zen", "browser": "Zen", "terminal": "Ghostty", "notes": "Notes",
    "settings": "System Settings", "system preferences": "System Settings", "finder": "Finder",
    "music": "Spotify", "messages": "Messages", "mail": "Mail", "calendar": "Calendar",
    "whatsapp": "WhatsApp", "code": "Visual Studio Code", "vscode": "Visual Studio Code",
}


@lru_cache(maxsize=1)
def installed_apps() -> dict[str, Path]:
    apps: dict[str, Path] = {}
    for d in APP_DIRS:
        if d.is_dir():
            for p in d.glob("*.app"):
                apps[p.stem] = p
    apps.setdefault("Finder", Path("/System/Library/CoreServices/Finder.app"))
    return apps


def resolve(name: str) -> str | None:
    """Fuzzy-map a spoken app name to an installed app name."""
    q = re.sub(r"^(?:the|my)\s+", "", name.strip().lower())
    q = re.sub(r"[\'’]", "", q)
    for key in (q, q.replace(" ", "")):
        if key in ALIASES and ALIASES[key] in installed_apps():
            return ALIASES[key]
    names = list(installed_apps())
    hit = process.extractOne(q, names, scorer=fuzz.WRatio, processor=str.lower, score_cutoff=72)
    if not hit:  # short spoken names ("zen") vs longer bundle names: try token match
        hit = process.extractOne(q, names, scorer=fuzz.token_set_ratio, processor=str.lower, score_cutoff=85)
    return hit[0] if hit else None


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)


def open_app(name: str) -> str:
    app = resolve(name)
    if not app:
        return f"I couldn't find an app called {name}."
    subprocess.run(["open", "-a", app], check=False)
    return f"Opening {app}."


def quit_app(name: str) -> str:
    app = resolve(name)
    if not app:
        return f"I couldn't find an app called {name}."
    _osascript(f'tell application "{app}" to quit')
    return f"Quit {app}."


def switch_to(name: str) -> str:
    app = resolve(name)
    if not app:
        return f"I couldn't find an app called {name}."
    _osascript(f'tell application "{app}" to activate')
    return f"Switched to {app}."


def frontmost_app() -> str:
    r = _osascript('tell application "System Events" to get name of first application process whose frontmost is true')
    return r.stdout.strip()
