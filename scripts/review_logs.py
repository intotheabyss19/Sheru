"""Review Sheru's real usage to drive the self-improvement loop — run this at the start of a session (or
nightly) to see WHAT to fix: failures, user corrections, and the intent mix.

Run:  uv run python scripts/review_logs.py
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sheru import config

J = Path(config.DATA_DIR) / "journal.jsonl"
entries = [json.loads(l) for l in J.read_text().splitlines() if l.strip()] if J.exists() else []
print(f"=== Sheru usage review — {len(entries)} logged turns ===\n")
if not entries:
    print("No journal yet. Use Sheru, then re-run."); sys.exit(0)

by = collections.Counter((e.get("tool") or e.get("action") or "?") for e in entries)
print("Intent mix (what Sheru is actually asked to do):")
for k, n in by.most_common(15):
    print(f"  {n:4}  {k}")

fails = [e for e in entries if e.get("ok") is False or e.get("feedback") == "negative"]
print(f"\n{len(fails)} FAIL / negative-feedback turns — the fix list:")
for e in fails[-25:]:
    fb = f" ({e['feedback']})" if e.get("feedback") and e["feedback"] != "unlabeled" else ""
    print(f"  IN '{(e.get('utterance') or '')[:46]}' -> [{e.get('action') or e.get('tool')}] "
          f"{(e.get('speech') or e.get('handoff') or '')[:46]}{fb}")

corr = [e for e in entries if e.get("note") == "correction-followup"]
if corr:
    print(f"\n{len(corr)} turns where the NEXT utterance corrected the action (implicit misroute):")
    for e in corr[-12:]:
        print(f"  '{(e.get('utterance') or '')[:50]}' -> [{e.get('action') or e.get('tool')}]")

# STT-garble heuristic: very short/again-repeated or non-ascii-heavy inputs that failed
print("\nHint: FAILs clustered on one intent = a grammar/prompt gap to fix; many corrections after the same "
      "phrasing = a routing bug; garbled inputs = STT (try SHERU_STT=whisper/sarvam for Hindi).")
