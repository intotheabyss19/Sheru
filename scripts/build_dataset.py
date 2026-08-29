#!/usr/bin/env python3
"""Phase 4 — build a labeled tool-calling dataset for fine-tuning Sheru's local router.

Produces the CANONICAL labeled form (one JSON object per line: utterance -> tool + arguments, or tool=null for
a spoken-answer/chat turn). A later `format_for_mlx` step turns this into the exact chat template the trainer
wants; keeping labeling and formatting separate means the seed corpus survives a change of training harness.

Sources, in order of trust:
  1. A curated, templated SEED corpus across every tool in tools.py (varied phrasings, slot-filled).
  2. Hard NEGATIVES — chit-chat / spoken-answer turns that must NOT call a tool.
  3. Real utterances from data/journal.jsonl that already carry a confident tool label.

Run:  uv run python scripts/build_dataset.py            # writes data/finetune/seed.jsonl + prints stats
"""
from __future__ import annotations

import json
import sys
from itertools import cycle
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "data" / "finetune" / "seed.jsonl"

APPS = ["spotify", "whatsapp", "discord", "obsidian", "brave", "safari", "notes", "calendar", "the terminal"]
SONGS = ["dandelions", "tum hi ho", "blinding lights", "kesariya", "despacito", "channa mereya", "levitating"]
QUERIES = ["best ramen in delhi", "python asyncio tutorial", "weather patterns", "cheap flights to goa",
           "how bees make honey", "the tallest mountain"]
PEOPLE = ["piyush", "satya", "mom", "aditi", "sourav"]
MSGS = ["I'm running late", "the meeting moved to 5", "happy birthday", "call me when free", "great work today"]


def _rows():
    """Yield (utterance, tool, arguments) triples — the labeled seed corpus."""
    def emit(templates, slots, tool, argfn):
        cyc = cycle(slots)
        for t in templates:
            s = next(cyc)
            yield t.format(x=s), tool, argfn(s)

    yield from emit(["open {x}", "open up {x}", "launch {x}", "can you open {x}", "start {x}", "fire up {x}"],
                    APPS, "open_app", lambda s: {"name": s.replace("the ", "")})
    yield from emit(["quit {x}", "close {x}", "kill {x}", "shut {x} down"],
                    APPS, "quit_app", lambda s: {"name": s.replace("the ", "")})
    yield from emit(["play {x}", "play {x} on spotify", "put on {x}", "can you play {x}", "i want to hear {x}"],
                    SONGS, "play_song", lambda s: {"query": s})
    yield from emit(["search for {x}", "google {x}", "look up {x}", "search the web for {x}"],
                    QUERIES, "web_search", lambda s: {"query": s})
    yield from emit(["show me pictures of {x}", "images of {x}", "show me photos of {x}"],
                    ["tigers", "the eiffel tower", "golden retrievers", "sunsets"], "image_search",
                    lambda s: {"query": s})
    yield from emit(["set volume to {x}", "volume {x}", "turn the volume to {x} percent", "make it {x} percent"],
                    ["20", "40", "55", "70", "100"], "set_volume", lambda s: {"percent": int(s)})
    for cmd in ["pause", "play", "next", "skip", "previous", "resume"]:
        yield cmd, "media", {"command": cmd}
    yield from emit(["set a timer for {x} minutes", "timer for {x} minutes", "give me a {x} minute timer"],
                    ["5", "10", "15", "25"], "set_timer", lambda s: {"seconds": int(s) * 60, "label": "timer"})
    yield from emit(["remember that {x}", "note that {x}", "keep in mind {x}"],
                    ["my wifi password is on the fridge", "i prefer tea over coffee", "the car service is due"],
                    "remember", lambda s: {"text": s})
    for p, m in zip(PEOPLE, cycle(MSGS)):
        yield f"message {p} that {m}", "draft_message", {"recipient": p, "message": m, "app": "whatsapp"}
        yield f"text {p} saying {m}", "draft_message", {"recipient": p, "message": m, "app": "whatsapp"}
    for p, a in zip(PEOPLE, ["boss", "madam", "chief", "captain", "sir"]):
        yield f"address {p} as {a}", "set_address", {"name": p, "address": a}
        yield f"refer to {p} as {a}", "set_address", {"name": p, "address": a}
    yield from emit(["ask claude to {x}", "can you {x}", "help me {x}"],
                    ["summarize this pdf", "write a python script to rename files", "refactor this function",
                     "explain quantum entanglement"], "ask_claude", lambda s: {"task": s})
    # hard negatives — spoken answers / chit-chat that must NOT fire a tool
    for u in ["hello", "hey there", "how are you", "thanks", "thank you", "who are you", "what can you do",
              "good morning", "tell me a joke", "you're the best", "never mind", "cool"]:
        yield u, None, None


def _from_journal():
    """Real utterances that already carry a confident, non-synthetic tool label."""
    jf = ROOT / "data" / "journal.jsonl"
    if not jf.exists():
        return
    seen = set()
    for line in jf.read_text().splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        u, tool = (d.get("utterance") or "").strip(), d.get("tool")
        if not u or u.startswith("[") or tool in (None, "chat") or u.lower() in seen or len(u) > 120:
            continue
        seen.add(u.lower())
        yield u, tool, d.get("args")


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows, counts = [], {}
    for src in (_rows(), _from_journal()):
        for u, tool, args in src:
            rows.append({"utterance": u, "tool": tool, "arguments": args})
            counts[tool] = counts.get(tool, 0) + 1
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"wrote {len(rows)} labeled examples -> {OUT.relative_to(ROOT)}")
    print(f"distinct tools: {len([k for k in counts if k])}  (+ {counts.get(None, 0)} negatives)")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4}  {k}")
    print("\nNext: many more real examples accrue as you use Sheru; a LoRA run needs ~700-1500 total. "
          "Format for the trainer with a format_for_mlx step, then mlx_lm.lora (local) or RunPod/Unsloth.")


if __name__ == "__main__":
    main()
