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


# Web services that are NOT installed apps here — "open X" for these goes to the default browser, not a failed
# app lookup. Only genuinely-installed apps (WhatsApp, Spotify, Mail, Discord, …) open natively; everything else
# is treated as a website. Sheru decides which is which by what's actually in /Applications, not a hardcoded list.
WEB_SERVICES = {
    "youtube": "https://www.youtube.com", "you tube": "https://www.youtube.com",
    "youtube music": "https://music.youtube.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "maps": "https://maps.google.com", "google maps": "https://maps.google.com",
    "twitter": "https://twitter.com", "x": "https://x.com", "linkedin": "https://www.linkedin.com",
    "instagram": "https://www.instagram.com", "insta": "https://www.instagram.com",
    "facebook": "https://www.facebook.com", "reddit": "https://www.reddit.com", "netflix": "https://www.netflix.com",
    "notion": "https://www.notion.so", "github": "https://github.com", "chatgpt": "https://chatgpt.com",
    "gemini": "https://gemini.google.com", "claude": "https://claude.ai", "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com", "prime video": "https://www.primevideo.com",
    "hotstar": "https://www.hotstar.com", "spotify web": "https://open.spotify.com",
    "whatsapp web": "https://web.whatsapp.com",
}


def open_app(name: str) -> str:
    app = resolve(name)
    if app:
        subprocess.run(["open", "-a", app], check=False)
        return f"Opening {app}."
    return open_web(name)                # not an installed app -> it's a website / web service


def open_web(name: str) -> str:
    """Open a non-installed target as a website in the user's DEFAULT browser (bare `open` honours the macOS
    default handler — Zen, Safari, whatever they set — not Sheru's automation browser)."""
    slug = re.sub(r"^(?:a|an|the|my)\s+", "", name.strip().lower()).strip().rstrip("?.!")
    if slug in WEB_SERVICES:
        url = WEB_SERVICES[slug]
    elif slug.startswith(("http://", "https://")):
        url = slug
    elif re.search(r"[a-z0-9-]+\.[a-z]{2,}(?:/\S*)?$", slug):     # already looks like a domain (netflix.com)
        url = "https://" + slug
    elif len(slug.split()) <= 2:
        url = "https://www." + re.sub(r"\s+", "", slug) + ".com"  # short brand name -> its site
    else:
        from . import web                                          # a descriptive phrase ("a wikipedia page
        return web.search(name)                                    # about X") -> search it, not a made-up domain
    subprocess.run(["open", url], check=False)                    # no -a -> the user's default browser
    return f"Opening {url.split('//', 1)[-1].split('/')[0]} in your browser."


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
