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


def _open(url: str) -> None:
    # -g keeps a search in the background (silent, Siri-like); no `-a` so it opens in the user's DEFAULT browser
    # (macOS default handler — Zen/Safari/whatever they set), not a hardcoded one.
    subprocess.run(["open", "-g", url], check=False)
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
