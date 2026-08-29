#!/usr/bin/env python3
"""Phase 4 — distill Claude's routing into training labels.

For each utterance, ask Claude (headless `claude -p`, subscription auth — same login the app uses) which ONE
Sheru tool to call (with arguments) or whether to just answer in speech. Claude is the teacher; its labels
become high-quality, diverse training data for the local 4B — exactly the open-ended phrasings the Tier-0
grammar misses. Appends to data/finetune/claude_labeled.jsonl in the same canonical form as build_dataset.py,
so format_for_mlx.py consumes both.

Usage:
  uv run python scripts/label_with_claude.py --from-journal --limit 40   # label real, unlabeled utterances
  uv run python scripts/label_with_claude.py --file utterances.txt       # one utterance per line
  uv run python scripts/label_with_claude.py --limit 10                  # built-in open-ended seed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "data" / "finetune" / "claude_labeled.jsonl"
CLAUDE = shutil.which("claude") or str(Path.home() / ".local/bin/claude")

DEFAULT_SEED = [
    "i'm bored, put on some lofi beats", "shoot piyush a text that i'll be 10 minutes late",
    "what's the score of the india match", "crank the volume up", "make it a lot quieter",
    "i wanna watch the new mkbhd video", "open that notes app", "who won the 2011 cricket world cup",
    "silence everything", "text mom i'll call her after dinner", "pull up the weather for tomorrow",
    "throw on some music", "what's elon musk up to lately", "give me a 20 minute focus timer",
    "play agar tum saath ho on spotify", "open youtube", "open netflix", "open my gmail",
    "message satya that the repo is ready", "set an alarm for quarter past seven", "wake me at half past six",
    "remind me to call the dentist tomorrow at four", "address gaurav as chief",
    "ask claude to write a python script that renames files", "what's the capital of australia",
    "increase the volume by 20 percent", "show me pictures of the himalayas", "play some arijit singh",
    "tell piyush i'll join the call in five", "open twitter", "put on channa mereya",
]


def _claude_env():
    from sheru import config
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE")}   # don't look like a nested session
    env.pop("ANTHROPIC_API_KEY", None)                                 # subscription auth only
    if config.CLAUDE_CONFIG_DIR:
        env["CLAUDE_CONFIG_DIR"] = config.CLAUDE_CONFIG_DIR             # the working login
    return env


# common key drift from the teacher -> the real schema key
_ALIASES = {"to": "recipient", "prompt": "task", "text": "message", "msg": "message", "song": "query",
            "app_name": "name", "application": "name", "volume": "percent", "level": "percent"}


def _normalize(tool: str, args: dict, valid: dict | None) -> dict:
    """Coerce the teacher's argument keys to the real tool schema; drop keys the tool doesn't accept."""
    if not valid or tool not in valid:
        return args
    keys, out = valid[tool], {}
    for k, v in (args or {}).items():
        nk = k if k in keys else _ALIASES.get(k, k)
        if nk in keys:
            out[nk] = v
    return out


def _label(utterance: str, tool_lines: str, env, valid: dict | None = None) -> dict | None:
    prompt = (
        "You are labeling training data for a local voice-assistant router named Sheru. Given a user utterance "
        "and the available tools, output ONLY a JSON object (no prose, no code fence) that is EITHER\n"
        '  {"tool": "<name>", "arguments": {...}}   -- call exactly one tool, or\n'
        '  {"say": "<short spoken reply>"}           -- no tool needed; a brief spoken answer.\n'
        "Prefer ask_claude for anything live/current/multi-step. Keep arguments minimal and correct.\n\n"
        f"Tools:\n{tool_lines}\n\nUtterance: \"{utterance}\"\n\nJSON:"
    )
    try:
        r = subprocess.run([CLAUDE, "-p", prompt], env=env, capture_output=True, text=True, timeout=90)
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    m = re.search(r"\{.*\}", (r.stdout or "").strip(), re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if d.get("tool"):
        return {"utterance": utterance, "tool": d["tool"],
                "arguments": _normalize(d["tool"], d.get("arguments") or {}, valid)}
    if "say" in d:
        return {"utterance": utterance, "tool": None, "arguments": {"say": d["say"]}}
    return None


def _utterances(args) -> list[str]:
    if args.file:
        return [l.strip() for l in Path(args.file).read_text().splitlines() if l.strip()]
    if args.from_journal:
        seen, out = set(), []
        for line in (ROOT / "data" / "journal.jsonl").read_text().splitlines():
            try:
                d = json.loads(line)
            except Exception:
                continue
            u = (d.get("utterance") or "").strip()
            if u and not u.startswith("[") and u.lower() not in seen and len(u) < 120:
                seen.add(u.lower())
                out.append(u)
        return out
    return DEFAULT_SEED


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-journal", action="store_true")
    ap.add_argument("--file")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    from sheru.tools import TOOLS

    def _params(t):
        return list(((t["function"].get("parameters") or {}).get("properties") or {}).keys())

    tool_lines = "\n".join(f'- {t["function"]["name"]}({", ".join(_params(t))}): {t["function"]["description"]}'
                           for t in TOOLS)
    valid = {t["function"]["name"]: set(_params(t)) for t in TOOLS}
    env = _claude_env()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set()                                    # skip utterances already labeled (idempotent re-runs)
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                done.add(json.loads(line)["utterance"].lower())
            except Exception:
                pass
    us = [u for u in _utterances(args) if u.lower() not in done][: args.limit]
    labeled = []
    for i, u in enumerate(us, 1):
        d = _label(u, tool_lines, env, valid)
        print(f"  [{i}/{len(us)}] {u[:44]:46} -> {(d['tool'] or 'say') if d else 'FAILED'}")
        if d:
            labeled.append(d)
    with OUT.open("a") as f:
        for d in labeled:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"appended {len(labeled)}/{len(us)} labels -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
