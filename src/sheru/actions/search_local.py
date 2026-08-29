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


def fetch_results(query: str, n: int = 6) -> list[tuple[str, str]]:
    """(title, snippet) pairs from DuckDuckGo's HTML endpoint — no API key, no browser."""
    import requests
    try:
        page = requests.get(
            "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query),
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                     "Accept-Language": "en-US,en;q=0.9"},
            timeout=8).text
    except Exception:
        return []
    titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', page, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
    out = []
    for t, s in zip(titles, snippets):
        t, s = _clean(t), _clean(s)
        if t and s:
            out.append((t, s))
        if len(out) >= n:
            break
    return out


def search_and_summarize(query: str, llm) -> str | None:
    """A 2-3 sentence spoken answer summarized from web snippets by the LOCAL model, or None to escalate."""
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
