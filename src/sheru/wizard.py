"""First-run setup wizard: introduces Sheru, requests + VERIFIES each permission, sets up integrations.

Runs in the terminal (`uv run sheru setup`) — the reliable place to grant permissions and paste keys. Every
permission is re-checked after you act, so nothing is assumed. A marker in data/ stops it nagging next launch.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config, permissions
from .actions import location, music

MARKER = config.DATA_DIR / "setup.json"

CAPABILITIES = [
    "Open / quit / switch apps            — “open Spotify”, “switch to Obsidian”",
    "Web search + summarize               — “search the best momos and summarize”",
    "Answer & chat (current info → Claude)— “what’s the weather”, “tell me a fun fact”",
    "Music / volume / timers              — “play Choo Lo”, “volume 40”, “timer 5 minutes”",
    "Draft & send messages (you confirm)  — “message Bob that I’m running late”",
    "Remember things about you            — “remember I prefer tea”",
    "Type silently or talk hands-free     — the Type-to-Sheru box, or “Hey Sheru …”",
    "Hand hard work to Claude Code        — research, code, files, multi-step tasks",
]

C = {"g": "\033[32m", "y": "\033[33m", "r": "\033[31m", "b": "\033[1m", "d": "\033[2m", "x": "\033[0m"}


def _ask(msg: str) -> str:
    try:
        return input(msg).strip()
    except (EOFError, KeyboardInterrupt):
        return "s"


def is_done() -> bool:
    try:
        return json.loads(MARKER.read_text()).get("done") is True
    except Exception:
        return False


def run(speak=None) -> None:
    say = speak or (lambda t: None)
    print(f"\n  🦁  {C['b']}Hi, I'm Sheru — let's get set up.{C['x']}\n")
    say("Hi, I'm Sheru. Let's get set up.")

    # ---- 1. Permissions (probe -> explain -> open pane -> RE-VERIFY) ----
    print(f"  {C['b']}Permissions{C['x']} — I need a few, like Siri does. I'll check each one.\n")
    for p in permissions.status():
        if p.status == "granted":
            print(f"    {C['g']}✓{C['x']} {p.label} — already granted")
            continue
        print(f"    {C['y']}•{C['x']} {C['b']}{p.label}{C['x']} — {p.why}")
        print(f"      {C['d']}Opening the setting… enable {p.label} for your terminal/Sheru, then come back.{C['x']}")
        permissions.request_prompt(p.key)
        while True:
            ans = _ask(f"      Press {C['b']}Enter{C['x']} once granted, or type {C['b']}s{C['x']} to skip: ").lower()
            if ans == "s":
                print(f"      {C['y']}Skipped{C['x']} — some features will be limited until you grant it.\n")
                break
            fresh = next((q for q in permissions.status() if q.key == p.key), None)
            if fresh and fresh.status == "granted":
                print(f"    {C['g']}✓{C['x']} {p.label} — granted, thanks!\n")
                break
            print(f"      {C['r']}Still not granted.{C['x']} Enable it in the window that opened, then Enter (or 's').")

    # ---- 2. Location ----
    cur = location.describe()
    print(f"  {C['b']}Location{C['x']} — used for “weather here”, local search, etc.")
    ans = _ask(f"    I have your location as {C['b']}{cur or 'unknown'}{C['x']}. "
               f"Press Enter to keep it, or type your city: ")
    if ans and ans.lower() != "s":
        config.update_profile("location", ans.title())
        print(f"    {C['g']}✓{C['x']} Set to {ans.title()}\n")
    else:
        print()

    # ---- 3. Spotify (optional) ----
    print(f"  {C['b']}Spotify{C['x']} — to play a specific song directly (e.g. “play Choo Lo”).")
    print(f"    {C['d']}Optional. Skip this and I'll still play songs through the Spotify web player in your")
    print(f"    browser (no keys needed) once Claude-in-Chrome is set up — see the note at the end.{C['x']}")
    if _ask("    Set up direct API playback now? (needs a free Spotify app) [y/N]: ").lower() == "y":
        import subprocess
        subprocess.run(["open", "https://developer.spotify.com/dashboard"], check=False)
        print(f"    {C['d']}Log in first, then click “Create app” (top-right). Any name; redirect URI")
        print(f"    http://localhost. Open the app → Settings to copy the Client ID and Secret.{C['x']}")
        cid = _ask("    Client ID (or Enter to skip): ")
        sec = _ask("    Client Secret (or Enter to skip): ") if cid else ""
        if cid and sec:
            config.update_profile("spotify_client_id", cid)
            config.update_profile("spotify_client_secret", sec)
            ok = music._token(cid, sec)
            print(f"    {C['g']}✓ Spotify connected.{C['x']}\n" if ok
                  else f"    {C['r']}Those keys didn't work — re-run setup to retry.{C['x']}\n")
        else:
            print(f"    {C['y']}Skipped — I'll open songs in Spotify's search instead.{C['x']}\n")
    else:
        print()

    # ---- 4. What I can do ----
    print(f"  {C['b']}Here's what I can do:{C['x']}")
    for c in CAPABILITIES:
        print(f"    • {c}")
    print(f"\n  Say {C['b']}“Hey Sheru”{C['x']} to talk, or use the Type-to-Sheru box. "
          f"Re-run this anytime with {C['b']}uv run sheru setup{C['x']}.\n")

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps({"done": True, "ts": time.time()}))
    say("All set. Say hey Sheru whenever you need me.")


def summary() -> str:
    """Non-interactive status line for the menu bar / logs."""
    st = permissions.status()
    granted = sum(1 for p in st if p.status == "granted")
    return f"{granted}/{len(st)} permissions granted"
