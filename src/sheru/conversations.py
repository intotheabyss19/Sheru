"""Conversation history: group the flat journal into time-gap 'sessions', star some to keep them, search
across them, and auto-expire anything older than a week that isn't starred.

A conversation = a run of turns with < GAP_S between them. Its id is the (integer) start timestamp, so it's
stable across restarts. Starred ids live in data/starred.json; prune() rewrites the journal keeping only
turns that are starred or within RETAIN_DAYS. Nothing here touches the UI — panel/menu call these.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import config

JOURNAL = config.DATA_DIR / "journal.jsonl"
STARS = config.DATA_DIR / "starred.json"

GAP_S = 30 * 60            # >30 min idle starts a new conversation
RETAIN_DAYS = 7           # unstarred conversations expire after a week


# ── low-level ──────────────────────────────────────────────────────────────────────────────────────
def _turns() -> list[dict]:
    """Real (non-internal) journal turns, oldest-first, each with a derived src ('local'|'claude')."""
    if not JOURNAL.exists():
        return []
    out = []
    for line in JOURNAL.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        u = (d.get("utterance") or "").strip()
        if not u or u.startswith("["):
            continue
        d["_u"] = u
        d["_src"] = "claude" if (d.get("handoff") or d.get("tier") == 2) else "local"
        d["_reply"] = (d.get("speech") or "").strip() or ("…handed to Claude" if d.get("handoff") else "")
        out.append(d)
    out.sort(key=lambda d: d.get("ts", 0))
    return out


def _group(turns: list[dict]) -> list[dict]:
    """Split turns into sessions on a >GAP_S gap. Newest session last."""
    sessions, cur = [], None
    for t in turns:
        ts = t.get("ts", 0)
        if cur is None or ts - cur["end"] > GAP_S:
            cur = {"id": int(ts), "start": ts, "end": ts, "turns": []}
            sessions.append(cur)
        cur["end"] = ts
        cur["turns"].append(t)
    return sessions


# ── stars ──────────────────────────────────────────────────────────────────────────────────────────
def _stars() -> set[int]:
    try:
        return set(json.loads(STARS.read_text()).get("starred", []))
    except Exception:
        return set()


def _save_stars(ids: set[int]) -> None:
    STARS.parent.mkdir(parents=True, exist_ok=True)
    STARS.write_text(json.dumps({"starred": sorted(ids)}))


def is_starred(sid: int) -> bool:
    return int(sid) in _stars()


def toggle_star(sid: int) -> bool:
    ids = _stars()
    sid = int(sid)
    if sid in ids:
        ids.discard(sid)
        starred = False
    else:
        ids.add(sid)
        starred = True
    _save_stars(ids)
    return starred


# ── labels ───────────────────────────────────────────────────────────────────────────────────────
def _label(ts: float) -> str:
    lt = time.localtime(ts)
    today = time.localtime()
    h = lt.tm_hour % 12 or 12
    ap = "AM" if lt.tm_hour < 12 else "PM"
    hm = f"{h}:{lt.tm_min:02d} {ap}"
    if (lt.tm_year, lt.tm_yday) == (today.tm_year, today.tm_yday):
        return f"Today {hm}"
    if lt.tm_yday == today.tm_yday - 1 and lt.tm_year == today.tm_year:
        return f"Yesterday {hm}"
    return time.strftime("%a %d %b ", lt) + hm


def _title(turns: list[dict]) -> str:
    utts = [t["_u"] for t in turns[:3]]
    s = ", ".join(utts)
    return (s[:52] + "…") if len(s) > 53 else s


# ── public API ─────────────────────────────────────────────────────────────────────────────────────
def list_sessions(limit: int = 60, query: str = "") -> list[dict]:
    """Conversations newest-first: {id, start, end, label, title, starred, n}. `query` filters by any
    word in an utterance or reply (case-insensitive)."""
    stars = _stars()
    sessions = _group(_turns())
    q = (query or "").strip().lower()
    rows = []
    for s in reversed(sessions):
        if q and not any(q in (t["_u"] + " " + t["_reply"]).lower() for t in s["turns"]):
            continue
        rows.append({"id": s["id"], "start": s["start"], "end": s["end"], "label": _label(s["start"]),
                     "title": _title(s["turns"]), "starred": s["id"] in stars, "n": len(s["turns"])})
        if len(rows) >= limit:
            break
    return rows


def session_turns(sid: int) -> list[dict]:
    """The chat turns of one conversation as panel bubbles: [{role, text, src, ts}, …] oldest-first."""
    sid = int(sid)
    for s in _group(_turns()):
        if s["id"] == sid:
            out = []
            for t in s["turns"]:
                out.append({"role": "you", "text": t["_u"], "ts": t.get("ts")})
                if t["_reply"]:
                    out.append({"role": "sheru", "text": t["_reply"], "src": t["_src"], "ts": t.get("ts")})
            return out
    return []


def prune(days: int = RETAIN_DAYS) -> int:
    """Drop journal turns older than `days`, EXCEPT those in a starred conversation. Returns lines removed."""
    if not JOURNAL.exists():
        return 0
    stars = _stars()
    cutoff = time.time() - days * 86400
    sessions = _group(_turns())
    keep_ids = {s["id"] for s in sessions if s["id"] in stars or s["end"] >= cutoff}
    ts_to_session = {round(t.get("ts", 0), 3): s["id"] for s in sessions for t in s["turns"]}
    kept, removed = [], 0
    for line in JOURNAL.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except Exception:
            kept.append(line)                              # never lose an unparseable line
            continue
        sid = ts_to_session.get(round(d.get("ts", 0), 3))
        recent = d.get("ts", 0) >= cutoff
        if (sid in keep_ids) if sid is not None else recent:
            kept.append(line)
        else:
            removed += 1
    if removed:
        JOURNAL.write_text("\n".join(kept) + ("\n" if kept else ""))
    return removed
