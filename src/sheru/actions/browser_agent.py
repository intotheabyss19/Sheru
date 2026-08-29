"""Real browser ACTIONS (not just opening a URL) — Lane A.

YouTube / YouTube-Music: resolve the first search result's video id and open the watch URL in the chosen
browser+profile (browser.py), so it autoplays and keeps playing in a normal tab (no login needed).
Gmail / LinkedIn: driven with Playwright on the real logged-in Brave profile (needs Brave closed + a one-time
login; send actions go through Sheru's confirm flow). Those are logged-in + TOS-sensitive, so they never
auto-send without a spoken/typed "yes".
"""
from __future__ import annotations

import re
import subprocess
import urllib.parse

from . import browser


def _press_play_soon(delay: float = 4.0) -> None:
    """Best-effort: after the watch page loads, bring the browser front and press 'k' (YouTube's play/pause) so
    the video actually STARTS — Chromium blocks silent autoplay until a user gesture. Needs Accessibility for
    System Events; if that's not granted it fails quietly and the tab is still open, just paused."""
    app = browser.current().get("browser", "Brave Browser")
    script = (f'delay {delay}\n'
              f'tell application "{app}" to activate\n'
              f'delay 0.6\n'
              f'tell application "System Events" to keystroke "k"')
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
        browser.launch(f"https://www.youtube.com/watch?v={vid}")
        return f"Playing {query} on YouTube in {browser.describe()}."
    browser.launch("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query))
    return f"I couldn't resolve the video, so I opened YouTube search for {query}."


def play_music(query: str) -> str:
    vid = _first_youtube_id(query, music=True)
    if vid:
        browser.launch(f"https://music.youtube.com/watch?v={vid}")
        return f"Playing {query} on YouTube Music."
    browser.launch("https://music.youtube.com/search?q=" + urllib.parse.quote(query))
    return f"I opened YouTube Music search for {query}."
