"""Structured local answers — precise, deterministic, no LLM, no key. Keeps the highest-value current-info
queries (money, weather, news) ON-DEVICE and EXACT instead of scraping + summarizing.

Each answerer returns a short spoken string, or None if the query isn't its shape / the fetch fails — so
search_local.search_and_summarize can try these first, then fall back to the scrape+summarize path, then Claude.

Sources (all keyless, free): Frankfurter (ECB FX), Open-Meteo (weather), Google News RSS (headlines).
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from . import location

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _get(url: str, timeout: float = 6) -> str | None:
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception:
        return None


# ── currency ─────────────────────────────────────────────────────────────────────────────────────
_CCY = {
    "dollar": "USD", "dollars": "USD", "usd": "USD", "buck": "USD", "bucks": "USD",
    "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "rupee": "INR", "rupees": "INR", "inr": "INR", "rs": "INR", "rupya": "INR", "rupaye": "INR",
    "pound": "GBP", "pounds": "GBP", "gbp": "GBP", "sterling": "GBP", "quid": "GBP",
    "yen": "JPY", "jpy": "JPY", "yuan": "CNY", "cny": "CNY", "rmb": "CNY", "renminbi": "CNY",
    "won": "KRW", "krw": "KRW", "franc": "CHF", "chf": "CHF", "aud": "AUD", "cad": "CAD",
    "nzd": "NZD", "sgd": "SGD", "hkd": "HKD", "dirham": "AED", "aed": "AED", "riyal": "SAR",
    "sar": "SAR", "ruble": "RUB", "rouble": "RUB", "rub": "RUB", "real": "BRL", "brl": "BRL",
    "peso": "MXN", "mxn": "MXN", "lira": "TRY", "try": "TRY", "rand": "ZAR", "zar": "ZAR",
    "baht": "THB", "thb": "THB", "ringgit": "MYR", "myr": "MYR", "krona": "SEK", "sek": "SEK",
}
_NUM = r"(\d+(?:\.\d+)?)"


def fx(query: str) -> str | None:
    """'100 dollars in rupees', 'convert 50 euro to inr', 'how much is 20 usd in gbp' -> exact converted amount."""
    q = query.lower()
    if not any(w in q for w in ("in ", " to ", "into", "convert", "worth", "exchange")):
        if "rate" not in q:
            return None
    codes = [(m.start(), _CCY[m.group(0)]) for m in re.finditer(r"[a-z]+", q) if m.group(0) in _CCY]
    if len(codes) < 2:
        return None
    frm, to = codes[0][1], codes[-1][1]
    if frm == to:
        return None
    m = re.search(_NUM, q)
    amount = float(m.group(1)) if m else 1.0
    data = _get(f"https://api.frankfurter.app/latest?amount={amount}&from={frm}&to={to}")
    if not data:
        return None
    import json
    try:
        rate = json.loads(data)["rates"][to]
    except Exception:
        return None
    amt_s = f"{amount:,.2f}".rstrip("0").rstrip(".")
    res_s = f"{rate:,.2f}"
    return f"{amt_s} {_spoken_ccy(frm)} is about {res_s} {_spoken_ccy(to)}."


_CCY_SPOKEN = {"USD": "US dollars", "EUR": "euros", "INR": "rupees", "GBP": "pounds", "JPY": "yen",
               "CNY": "yuan", "AUD": "Australian dollars", "CAD": "Canadian dollars"}


def _spoken_ccy(code: str) -> str:
    return _CCY_SPOKEN.get(code, code)


# ── weather ──────────────────────────────────────────────────────────────────────────────────────
_WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "foggy", 48: "foggy",
        51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain",
        65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
        75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "heavy showers",
        85: "snow showers", 86: "snow showers", 95: "thunderstorms", 96: "thunderstorms with hail",
        99: "thunderstorms with hail"}
_WEATHER_Q = re.compile(r"\b(weather|temperature|forecast|how (?:hot|cold|warm)|is it (?:raining|going to rain)|"
                        r"raining|rainfall|humidity|wind)\b", re.I)


def _geocode(name: str) -> tuple[float, float, str] | None:
    data = _get("https://geocoding-api.open-meteo.com/v1/search?count=1&name=" + urllib.parse.quote(name))
    if not data:
        return None
    import json
    try:
        r = json.loads(data)["results"][0]
        return r["latitude"], r["longitude"], r["name"]
    except Exception:
        return None


def weather(query: str) -> str | None:
    """'weather today', 'weather in tokyo', 'is it going to rain' -> current temp + condition + today's range."""
    if not _WEATHER_Q.search(query):
        return None
    import json
    place = None
    m = re.search(r"\b(?:in|at|for)\s+([a-z][a-z\s]+?)(?:\s+(?:today|now|tomorrow|right now))?\s*[?.!]*$",
                  query, re.I)
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in ("my location", "here", "my area", "the moment"):
            place = cand
    if place:
        geo = _geocode(place)
        if not geo:
            return None
        lat, lon, label = geo
    else:
        loc = location.where()
        if not loc.get("lat"):
            return None
        lat, lon, label = loc["lat"], loc["lon"], loc.get("city") or "your area"
    data = _get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=temperature_2m,weather_code&daily=temperature_2m_max,temperature_2m_min"
                "&timezone=auto&forecast_days=1")
    if not data:
        return None
    try:
        d = json.loads(data)
        cur = d["current"]
        t = round(cur["temperature_2m"])
        cond = _WMO.get(cur["weather_code"], "")
        hi = round(d["daily"]["temperature_2m_max"][0])
        lo = round(d["daily"]["temperature_2m_min"][0])
    except Exception:
        return None
    cond_s = f", {cond}" if cond else ""
    return f"It's {t} degrees in {label} right now{cond_s}. Today's high is {hi}, low {lo}."


# ── news ─────────────────────────────────────────────────────────────────────────────────────────
_NEWS_Q = re.compile(r"\b(news|headlines?|what'?s happening|latest updates?|top stories)\b", re.I)


def news(query: str) -> str | None:
    """'what's the news', 'news about AI', 'top headlines' -> the top few headlines from Google News RSS."""
    if not _NEWS_Q.search(query):
        return None
    topic = re.sub(r"\b(what'?s|whats|what|is|are|the|a|an|latest|today'?s?|now|current|recent|top|show|tell|"
                   r"give|me|us|any|some|about|on|of|for|please|can|you|there|s|news|headlines?|stories|story|"
                   r"updates?|happening|going)\b", " ", query, flags=re.I)
    topic = re.sub(r"[^\w\s]", " ", topic)
    topic = re.sub(r"\s+", " ", topic).strip()
    has_topic = len(topic) >= 2                            # keep short topics like 'AI', 'US', 'UK'
    base = "https://news.google.com/rss"
    url = (base + "/search?q=" + urllib.parse.quote(topic) + "&" if has_topic else base + "?") + \
          "hl=en-IN&gl=IN&ceid=IN:en"
    data = _get(url, timeout=7)
    if not data:
        return None
    items = re.findall(r"<item>(.*?)</item>", data, re.S)
    heads = []
    for it in items[:5]:
        tm = re.search(r"<title>(.*?)</title>", it, re.S)
        if tm:
            title = html.unescape(re.sub(r"<[^>]+>", "", tm.group(1))).strip()
            title = re.sub(r"\s+-\s+[^-]+$", "", title)          # drop the trailing " - Publisher"
            if title:
                heads.append(title)
        if len(heads) >= 3:
            break
    if not heads:
        return None
    lead = f"Top news about {topic}: " if has_topic else "Here's the top news. "
    return lead + " ".join(f"{i}. {h}." for i, h in enumerate(heads, 1))


# ── wikipedia (facts about people/places/things) ──────────────────────────────────────────────────
_WIKI_Q = re.compile(r"^\s*(?:who|what)(?:'?s| is| are| was| were)\s+(.+?)\??$|"
                     r"^\s*tell me about\s+(.+?)\??$|^\s*(.+?)\s+wikipedia\s*$", re.I)
_WIKI_SKIP = re.compile(r"\b(weather|temperature|news|price|stock|rate|score|today|now|latest|happening|"
                        r"time|date|going to|worth|cost)\b", re.I)


def wiki(query: str) -> str | None:
    """'who is Ada Lovelace', 'what is a black hole', 'tell me about the Eiffel Tower' -> a crisp Wikipedia summary."""
    if _WIKI_SKIP.search(query):                           # live/current or already handled above — not encyclopedic
        return None
    m = _WIKI_Q.match(query.strip())
    if not m:
        return None
    topic = next((g for g in m.groups() if g), "").strip()
    topic = re.sub(r"^(a|an|the)\s+", "", topic, flags=re.I).strip()
    if len(topic) < 2 or len(topic.split()) > 8:
        return None
    words = set(re.findall(r"[a-z]+", topic.lower()))
    if re.search(r"\d", topic) and (words & set(_CCY)):    # a currency/amount query — fx's job, never Wikipedia
        return None
    import json
    # resolve the best title first (handles redirects, casing, 'who is' phrasings)
    srch = _get("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit=1&srsearch="
                + urllib.parse.quote(topic))
    title = topic
    if srch:
        try:
            hits = json.loads(srch)["query"]["search"]
            if hits:
                title = hits[0]["title"]
        except Exception:
            pass
    data = _get("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_")))
    if not data:
        return None
    try:
        d = json.loads(data)
    except Exception:
        return None
    if d.get("type", "").endswith("disambiguation"):
        return None
    extract = (d.get("extract") or "").strip()
    if not extract:
        return None
    sents = re.split(r"(?<=[.!?])\s+", extract)             # keep it to ~2 spoken sentences
    return " ".join(sents[:2]).strip()


# ── dispatcher ───────────────────────────────────────────────────────────────────────────────────
def answer(query: str) -> str | None:
    """Try each structured answerer; return the first precise hit, or None to fall back to scrape+summarize."""
    for fn in (fx, weather, news, wiki):
        try:
            r = fn(query)
        except Exception:
            r = None
        if r:
            return r
    return None
