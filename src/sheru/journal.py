"""Interaction journal — the raw material for Sheru's self-improvement loop (KB-style).

Every handled command is appended as one JSON line. A feedback signal is attached to the *previous*
entry when the next utterance looks like a correction/repeat/cancel (implicit negative), or when the
user explicitly confirms/denies. Nightly, `claude -p` curates these into labeled training pairs.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from . import config

JOURNAL = Path(config.DATA_DIR) / "journal.jsonl"

# implicit negative feedback on the previous turn
_CORRECTION = re.compile(
    r"\b(no|nope|not that|wrong|that'?s wrong|i (?:said|meant)|actually|instead|undo|that'?s not)\b", re.I)
_CANCEL = re.compile(r"\b(stop|cancel|never ?mind)\b", re.I)


def recent_pairs(n: int = 25) -> list[tuple[str, str]]:
    """(utterance, reply) pairs from the PERSISTENT journal, newest-first — so the panel can show real past
    conversations across restarts (the in-memory history is wiped each launch). Skips internal '[...]' entries
    and empties; for a Claude hand-off (no stored answer) shows the spoken ack or a marker."""
    if not JOURNAL.exists():
        return []
    pairs: list[tuple[str, str]] = []
    for line in JOURNAL.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        u = (d.get("utterance") or "").strip()
        if not u or u.startswith("["):
            continue
        reply = (d.get("speech") or "").strip() or ("…handed to Claude" if d.get("handoff") else "")
        pairs.append((u, reply))
    return list(reversed(pairs))[:n]


class Journal:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict | None = None
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, utterance: str, tier: int, tool: str | None, args: dict | None,
               speech: str, handoff: str | None, ts: float, latency: float | None = None,
               stt_latency: float | None = None) -> dict:
        # implicit feedback: does THIS utterance correct the PREVIOUS turn?
        if self._last is not None:
            if _CORRECTION.search(utterance):
                self._flush(self._last, feedback="negative", note="correction-followup")
            elif _CANCEL.search(utterance) and self._last.get("handoff"):
                self._flush(self._last, feedback="negative", note="cancelled")
            else:
                self._flush(self._last, feedback="unlabeled")
        # what Sheru DID: the concrete action + a short outcome, so the log shows input -> action, not just input
        action = tool or ("claude" if handoff else "chat")
        detail = (handoff or speech or "").strip()
        ok = not re.search(r"\b(couldn'?t|can'?t|failed|no such|didn'?t|not found|i don'?t have|ran into a problem)\b",
                           speech or "", re.I)
        entry = {"ts": round(ts, 3), "utterance": utterance, "tier": tier, "tool": tool, "action": action,
                 "args": args, "speech": speech, "handoff": handoff, "ok": ok, "feedback": None}
        if latency is not None: entry["latency"] = round(latency, 2)
        if stt_latency is not None: entry["stt"] = round(stt_latency, 2)
        self._append_readable(ts, utterance, action, detail, ok)
        self._last = entry
        return entry

    def _append_readable(self, ts: float, utterance: str, action: str, detail: str, ok: bool) -> None:
        """A human-friendly one-line-per-turn log (input -> what Sheru did), easy to `tail` and review."""
        try:
            mark = "ok " if ok else "FAIL"
            line = (f"{time.strftime('%H:%M:%S', time.localtime(ts))} [{mark}] "
                    f"IN: {utterance!r:.80}  ->  DID: [{action}] {detail[:90]}\n")
            with self._lock:
                with open(Path(config.DATA_DIR) / "actions.log", "a") as f:
                    f.write(line)
        except Exception:
            pass

    def label_last(self, feedback: str, note: str = "") -> None:
        """Explicit feedback hook (e.g. a voiced 'yes that's right' / 'no')."""
        if self._last is not None:
            self._flush(self._last, feedback=feedback, note=note)
            self._last = None

    def flush(self) -> None:
        if self._last is not None:
            self._flush(self._last, feedback=self._last.get("feedback") or "unlabeled")
            self._last = None

    def _flush(self, entry: dict, feedback: str, note: str = "") -> None:
        entry = {**entry, "feedback": feedback}
        if note:
            entry["note"] = note
        with self._lock:
            with open(JOURNAL, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
