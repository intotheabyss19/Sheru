"""Browser + profile control for agentic web actions.

Picks which Chromium browser (Brave by default — it holds Yash's logged-in profiles + the Claude-in-Chrome
extension) and which PROFILE (piyush / moon / ...) Sheru drives, and launches it (optionally with a
remote-debugging port so Playwright can attach to the real logged-in session). Profiles are discovered live
from the browser's Local State, so the spoken name ("piyush") maps to the right --profile-directory.

Simple "open this website" stays in web.py (Zen). This module is for the automation browser (Brave/piyush).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rapidfuzz import fuzz, process

# spoken browser name -> macOS app name
APP = {"zen": "Zen", "brave": "Brave Browser", "chrome": "Google Chrome", "chromium": "Brave Browser",
       "the browser": "Brave Browser", "browser": "Brave Browser"}
# Chromium user-data roots (for profile discovery + --profile-directory launching)
_SUPPORT = {
    "Brave Browser": Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser",
    "Google Chrome": Path.home() / "Library/Application Support/Google/Chrome",
}
CDP_PORT = 9222   # remote-debugging port for Playwright to attach to the real profile (Chrome 136+ needs a non-Default dir)

# default automation target: Brave + Piyush (has the logins + Claude-in-Chrome)
_state = {"browser": "Brave Browser", "profile_dir": "Profile 2", "profile_name": "Piyush"}


def _profiles(app: str) -> dict[str, str]:
    """spoken-name(lower) -> profile-directory (e.g. 'piyush' -> 'Profile 2'), read live from Local State."""
    base = _SUPPORT.get(app)
    if not base:
        return {}
    try:
        ic = json.loads((base / "Local State").read_text())["profile"]["info_cache"]
        return {(v.get("name") or d).strip().lower(): d for d, v in ic.items()}
    except Exception:
        return {}


def set_browser(name: str) -> str:
    app = APP.get(name.strip().lower())
    if not app:
        return f"I don't have {name}. I can use Zen, Brave, or Chrome."
    _state["browser"] = app
    if app not in _SUPPORT:                       # Zen has no chromium profile dir
        _state["profile_dir"] = None
    return f"Okay, I'll use {app}."


def set_profile(name: str, app: str | None = None) -> str:
    app = app or _state["browser"]
    if app not in _SUPPORT:
        app = "Brave Browser"                     # profiles only make sense on the chromium browsers
    profs = _profiles(app)
    if not profs:
        return f"I can't see any {app} profiles."
    hit = process.extractOne(name.strip().lower(), list(profs), scorer=fuzz.WRatio, score_cutoff=55)
    if not hit:
        return f"No {app} profile like {name}. I see: {', '.join(p.title() for p in profs)}."
    _state.update(browser=app, profile_dir=profs[hit[0]], profile_name=hit[0].title())
    launch()
    return f"Switched to {hit[0].title()}'s profile in {app.replace(' Browser','')}."


def launch(url: str | None = None, debugging: bool = False) -> None:
    """Open the current browser+profile (optionally at a URL, optionally with the CDP port for Playwright)."""
    app = _state["browser"]
    extra: list[str] = []
    if app in _SUPPORT and _state.get("profile_dir"):
        extra.append(f"--profile-directory={_state['profile_dir']}")
        if debugging:
            extra.append(f"--remote-debugging-port={CDP_PORT}")
    if url:
        extra.append(url)
    subprocess.Popen(["open", "-na", app, "--args", *extra] if extra else ["open", "-a", app])


def current() -> dict:
    return dict(_state)


def describe() -> str:
    return f"{_state['browser'].replace(' Browser','')} ({_state.get('profile_name') or 'default'} profile)"
