"""Instant memory — facts & preferences Sheru recalls immediately, like the user's knowledge base.

This is retrieval, not weight-learning: "remember I prefer X" is stored as a line and the relevant
lines are injected into the prompt. Reliable, reversible, and effective the same second — the right
mechanism for facts. (Skill/style improvement is the separate periodic fine-tune loop.)
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from rapidfuzz import fuzz

from . import config

STORE = Path(config.DATA_DIR) / "memory.jsonl"


class Memory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict] = []
        STORE.parent.mkdir(parents=True, exist_ok=True)
        if STORE.exists():
            self._items = [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]

    def remember(self, text: str, kind: str = "fact") -> str:
        item = {"text": text.strip(), "kind": kind, "ts": round(time.time(), 1)}
        with self._lock:
            self._items.append(item)
            with open(STORE, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return "Got it, I'll remember that."

    def recall(self, query: str, k: int = 4, floor: int = 55) -> list[str]:
        scored = [(fuzz.token_set_ratio(query, it["text"]), it["text"]) for it in self._items]
        scored = [(s, t) for s, t in scored if s >= floor]
        scored.sort(reverse=True)
        return [t for _, t in scored[:k]]

    def context_block(self, query: str, small: int = 30) -> str:
        # While the store is small, inject everything (like MEMORY.md loads whole) — reliable recall.
        # Once it grows past `small`, switch to fuzzy retrieval of the most relevant lines.
        if not self._items:
            return ""
        if len(self._items) <= small:
            lines = [it["text"] for it in self._items]
        else:
            lines = self.recall(query, k=8, floor=45)
        from . import config
        head = f"Things you know about {config.USER_NAME}:"
        return (head + "\n- " + "\n- ".join(lines)) if lines else ""

    def all(self) -> list[dict]:
        return list(self._items)
