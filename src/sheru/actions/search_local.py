"""Local web search + summarize — keep current-info queries ON-DEVICE.

Fetches result snippets over plain HTTP (DuckDuckGo HTML, no API key) and summarizes them with the LOCAL model,
so "what's the news", "look up X", "who won…" don't escalate to Claude. Only the raw fetch touches the network;
the reasoning is the local 4B. Returns None to let the caller fall back to Claude when it genuinely can't answer.
"""
from __future__ import annotations

import html
import re
import urllib.parse

_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAG.sub("", s)).strip()


_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Accept-Language": "en-US,en;q=0.9"}


def _fetch_html(query: str) -> list[tuple[str, str]]:
    """DuckDuckGo HTML endpoint — rich (title, snippet) pairs."""
    import requests
    page = requests.get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
                        headers=_UA, timeout=8).text
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', page, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    return [(_clean(t), _clean(s)) for t, s in zip(titles, snippets)]


def _fetch_lite(query: str) -> list[tuple[str, str]]:
    """DuckDuckGo Lite — a different layout/host, used when the HTML endpoint is blocked or empty."""
    import requests
    page = requests.get("https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query),
                        headers=_UA, timeout=8).text
    links = re.findall(r'<a[^>]*\brel="nofollow"[^>]*>(.*?)</a>', page, re.S)
    snips = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', page, re.S)
    if snips:
        return [(_clean(t), _clean(s)) for t, s in zip(links, snips)]
    return [(_clean(t), _clean(t)) for t in links]         # titles only — still useful context for the summarizer


def fetch_results(query: str, n: int = 6) -> list[tuple[str, str]]:
    """(title, snippet) pairs — no API key, no browser. Falls back across endpoints so a single block
    doesn't force an escalation to Claude."""
    for fetch in (_fetch_html, _fetch_lite):
        try:
            pairs = fetch(query)
        except Exception:
            pairs = []
        out = [(t, s) for t, s in pairs if t and s][:n]
        if out:
            return out
    return []


def search_and_summarize(query: str, llm) -> str | None:
    """A precise structured answer (FX/weather/news) when possible, else a 2-3 sentence spoken summary of web
    snippets by the LOCAL model, or None to escalate."""
    from . import structured
    exact = structured.answer(query)                       # deterministic, exact, no LLM — try first
    if exact:
        return exact
    if llm is None:
        return None
    results = fetch_results(query)
    if not results:
        return None
    context = "\n".join(f"- {t}: {s}" for t, s in results)
    ans = llm.answer(
        f"Question: {query}\n\nSearch results:\n{context}",
        extra_system=("Answer the question using ONLY these search results. Be concise: at most 3 short spoken "
                      "sentences, no preamble. If the results do not contain the answer, reply exactly: NOANSWER."))
    if not ans or "NOANSWER" in ans.upper():
        return None
    return ans.strip()
