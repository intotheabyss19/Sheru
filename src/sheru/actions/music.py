"""Play a specific song on Spotify.

Direct play needs a track URI. With Spotify API creds (client_id/secret in data/profile.json, free to
create) we search + play the exact track via AppleScript. Without creds we open the in-app search so the
song is right there to press play.
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
import urllib.request

from .. import config


def _creds() -> tuple[str, str] | None:
    p = config._profile() if hasattr(config, "_profile") else {}
    cid, sec = p.get("spotify_client_id"), p.get("spotify_client_secret")
    return (cid, sec) if cid and sec else None


def _token(cid: str, sec: str) -> str | None:
    import base64
    auth = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    req = urllib.request.Request("https://accounts.spotify.com/api/token",
                                 data=b"grant_type=client_credentials",
                                 headers={"Authorization": f"Basic {auth}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read())["access_token"]
    except Exception:
        return None


def _search_uri(query: str, token: str, market: str = "IN"):
    """Return (uri, 'Song by Artist', confidence 0-100) for the best match, or None."""
    from rapidfuzz import fuzz
    q = urllib.parse.urlencode({"q": query, "type": "track", "limit": 8, "market": market})
    req = urllib.request.Request(f"https://api.spotify.com/v1/search?{q}",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            items = json.loads(r.read())["tracks"]["items"]
    except Exception:
        return None
    if not items:
        return None
    ql = query.lower()
    def parts(t):
        name = t["name"].lower()
        lead = t["artists"][0]["name"].lower()   # "X's version" == X is the lead artist
        title_s = max(fuzz.token_set_ratio(ql, name), fuzz.partial_ratio(ql, name))
        # does the query explicitly name this track's LEAD artist? (same title, different lead = different version)
        lead_named = fuzz.partial_ratio(lead, ql) >= 85
        rank = title_s + (30 if lead_named else 0)   # version led by the named artist wins ties
        return title_s, rank
    best = max(items, key=lambda t: parts(t)[1])
    title_s = parts(best)[0]   # gate on the real title match, not the artist bonus
    return best["uri"], f"{best['name']} by {best['artists'][0]['name']}", title_s


def _resolve_web(query: str) -> str | None:
    """Find a spotify:track: URI without API creds by scraping a web search (best-effort)."""
    import re
    q = urllib.parse.quote(f"{query} spotify track")
    req = urllib.request.Request("https://html.duckduckgo.com/html/?q=" + q,
                                 headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)"})
    try:
        with urllib.request.urlopen(req, timeout=7) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception:
        return None
    m = re.search(r"open\.spotify\.com(?:%2F|/)track(?:%2F|/)([A-Za-z0-9]{22})", html)
    return f"spotify:track:{m.group(1)}" if m else None


def _play_uri(uri: str, label: str) -> str:
    tid = uri.rsplit(":", 1)[-1]                                   # 22-char track id
    subprocess.run(["open", "-g", "-a", "Spotify"], check=False)   # ensure app running, don't steal focus
    subprocess.run(["osascript", "-e", f'tell application "Spotify" to play track "{uri}"'], capture_output=True)
    # cold-start can leave OUR track loaded-but-paused. Resume ONLY after confirming it's the current track —
    # a blind 'play' before that would resume Spotify's radio/context and hijack to a different song.
    for _ in range(15):                                            # ~3 s max
        out = subprocess.run(
            ["osascript", "-e",
             'tell application "Spotify" to (id of current track) & "|" & (player state as string)'],
            capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()
        cur_id, _, state = out.partition("|")
        if tid in cur_id:                                         # our track is the current one
            if state != "playing":
                subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'], capture_output=True)
            break
        time.sleep(0.2)
    return f"Playing {label} on Spotify."


def resolve_uri(query: str):
    """Return (uri, 'Song by Artist') only for a CONFIDENT API match; else None -> Claude resolves it."""
    creds = _creds()
    if creds:
        token = _token(*creds)
        if token:
            hit = _search_uri(query, token)
            if hit and hit[2] >= 72:          # confident enough that the top match is really this song
                return hit[0], hit[1]
    return None


def play_song(query: str) -> str:
    hit = resolve_uri(query)
    if hit:
        return _play_uri(hit[0], hit[1])
    return "__RESOLVE_WITH_CLAUDE__"    # signal: router/app should delegate resolution to Claude


# ── playlists (AppleScript plays a playlist URI directly — no Spotify login needed; Sheru just needs the URI,
#    which it learns once from a share link) ─────────────────────────────────────────────────────────────────
import re

_PLAYLISTS = config.DATA_DIR / "playlists.json"


def _load_playlists() -> dict:
    try:
        return json.loads(_PLAYLISTS.read_text())
    except Exception:
        return {}


def _playlist_uri(link: str) -> str | None:
    """spotify:playlist:ID from a share link (https://open.spotify.com/playlist/ID?..) or a URI."""
    m = re.search(r"playlist[:/]([A-Za-z0-9]{22})", link or "")
    return f"spotify:playlist:{m.group(1)}" if m else None


def remember_playlist(name: str, link: str) -> str | None:
    """Teach Sheru a playlist: name -> URI, stored in data/playlists.json. Returns the URI or None."""
    uri = _playlist_uri(link)
    if not uri:
        return None
    d = _load_playlists()
    d[name.strip().lower()] = uri
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _PLAYLISTS.write_text(json.dumps(d, ensure_ascii=False))
    return uri


def play_playlist(name: str) -> str:
    """Play a taught playlist via AppleScript (no login). '__NEED_PLAYLIST__' if it isn't known yet."""
    d = _load_playlists()
    key = name.strip().lower()
    uri = d.get(key)
    if uri is None and d:                        # fuzzy: 'bhajan'/'my bhajans' -> the saved 'bhajans'
        try:
            from rapidfuzz import fuzz
            best = max(d, key=lambda k: fuzz.partial_ratio(key, k))
            if fuzz.partial_ratio(key, best) >= 70:
                uri, key = d[best], best
        except Exception:
            pass
    if uri is None:
        return "__NEED_PLAYLIST__"
    subprocess.run(["open", "-g", "-a", "Spotify"], check=False)
    subprocess.run(["osascript", "-e", f'tell application "Spotify" to play track "{uri}"'], capture_output=True)
    return f"Playing your {key} playlist on Spotify."
