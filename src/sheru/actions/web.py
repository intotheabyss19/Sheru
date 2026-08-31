"""Browser actions: search, image search, Zen profiles. Deterministic — URLs, not clicks."""
from __future__ import annotations

import configparser
import subprocess
from urllib.parse import quote_plus

from .. import config
from . import location

_state = {"engine": "duckduckgo", "last_query": None, "last_url": None}


def set_search_engine(name: str) -> str:
    key = name.strip().lower().replace(" ", "")
    key = {"duckduckgo": "duckduckgo", "duck": "duckduckgo", "ddg": "duckduckgo"}.get(key, key)
    if key not in config.SEARCH_ENGINES:
        return f"I don't know the search engine {name}."
    _state["engine"] = key
    return f"Using {key.capitalize()} for searches."


def _open(url: str, background: bool = False) -> None:
    # Explicit user opens/searches come to the FOREGROUND (Yash: "all browser requests should bring the window to
    # focus"). Sheru's own implicit lookups don't use this — they scrape + summarize. `background=True` is kept for
    # any silent case. No `-a` so it opens in the user's DEFAULT browser (Zen/Safari/whatever), not a hardcoded one.
    subprocess.run(["open"] + (["-g"] if background else []) + [url], check=False)
    _state["last_url"] = url


def search(query: str, engine: str | None = None) -> str:
    eng = engine or _state["engine"]
    query = location.localize(query)
    _state["last_query"] = query
    _open(config.SEARCH_ENGINES[eng].format(q=quote_plus(query)))
    return f"Searching {eng.capitalize()} for {query}."


def image_search(query: str, engine: str | None = None) -> str:
    eng = engine or _state["engine"]
    query = location.localize(query)
    _state["last_query"] = query
    _open(config.IMAGE_SEARCH[eng].format(q=quote_plus(query)))
    return f"Showing images of {query}."


def open_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    _open(url)
    return f"Opening {url.split('//', 1)[1].split('/')[0]}."


# "search X on <site>" opens the site's OWN search results, not a web search for "X on <site>". India-first.
SITE_SEARCH = {
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "myntra": "https://www.myntra.com/{q}",
    "snapdeal": "https://www.snapdeal.com/search?keyword={q}",
    "ebay": "https://www.ebay.in/sch/i.html?_nkw={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
}


def site_search(query: str, sites: list[str]) -> str:
    """Open the query's search results on each named site (foreground); falls back to a web search if none match."""
    opened = []
    for s in sites:
        tmpl = SITE_SEARCH.get(s)
        if tmpl:
            _open(tmpl.format(q=quote_plus(query)))
            opened.append(s.title())
    if not opened:
        return search(query)
    return f"Searching {' and '.join(opened)} for {query}."


def zen_profiles() -> list[str]:
    ini = configparser.ConfigParser()
    ini.read(config.ZEN_PROFILES_INI)
    return [ini[s]["Name"] for s in ini.sections() if s.startswith("Profile") and "Name" in ini[s]]


def switch_profile(name: str) -> str:
    from rapidfuzz import process, fuzz

    names = zen_profiles()
    hit = process.extractOne(name, names, scorer=fuzz.WRatio, score_cutoff=60)
    if not hit:
        return f"No Zen profile like {name}. I know: {', '.join(names)}."
    # Firefox-style: a second instance with another profile needs --no-remote... Zen honours -P.
    subprocess.run(["open", "-na", config.BROWSER_APP, "--args", "-P", hit[0], "--no-remote"], check=False)
    return f"Opening Zen with the {hit[0]} profile."


def last_query() -> str | None:
    return _state["last_query"]
