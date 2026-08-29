"""Real browser ACTIONS (not just opening a URL) — Lane A.

YouTube / YouTube-Music: resolve the first search result's video id and open the watch URL in the user's
DEFAULT browser (`open <url>`), then press 'k' so it actually plays (autoplay is gesture-gated). No login needed.
Gmail / LinkedIn: driven with Playwright on the real logged-in Brave profile (needs Brave closed + a one-time
login; send actions go through Sheru's confirm flow). Those are logged-in + TOS-sensitive, so they never
auto-send without a spoken/typed "yes".
"""
from __future__ import annotations

import re
import subprocess
import urllib.parse


def _press_play_soon(delay: float = 4.0) -> None:
    """Best-effort: after the watch page loads, press 'k' (YouTube's play) so the video actually STARTS —
    Chromium/Firefox block silent autoplay until a gesture. `open <url>` already foregrounds the DEFAULT browser,
    so we send the key to the frontmost app. Needs Accessibility; fails quietly (tab still opens, just paused)."""
    script = f'delay {delay}\ntell application "System Events" to keystroke "k"'
    try:
        subprocess.Popen(["osascript", "-e", script],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _first_youtube_id(query: str, music: bool = False) -> str | None:
    """First video id from a YouTube search, by scraping ytInitialData from the results HTML (no API key)."""
    import requests
    if music:
        url = "https://music.youtube.com/search?q=" + urllib.parse.quote(query)
    else:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        html = requests.get(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en"},
                            timeout=10).text
        m = re.search(r'"videoId":"([\w-]{11})"', html)
        return m.group(1) if m else None
    except Exception:
        return None


def play_youtube(query: str) -> str:
    vid = _first_youtube_id(query)
    if vid:
        subprocess.run(["open", f"https://www.youtube.com/watch?v={vid}"], check=False)   # default browser
        _press_play_soon()
        return f"Playing {query} on YouTube."
    subprocess.run(["open", "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)], check=False)
    return f"I couldn't find the exact video, so I opened a YouTube search for {query}."


def play_music(query: str) -> str:
    vid = _first_youtube_id(query, music=True)
    if vid:
        subprocess.run(["open", f"https://music.youtube.com/watch?v={vid}"], check=False)   # default browser
        _press_play_soon()
        return f"Playing {query} on YouTube Music."
    subprocess.run(["open", "https://music.youtube.com/search?q=" + urllib.parse.quote(query)], check=False)
    return f"I opened YouTube Music search for {query}."
