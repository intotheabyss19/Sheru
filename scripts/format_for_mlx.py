#!/usr/bin/env python3
"""Phase 4 — format the labeled dataset into mlx_lm LoRA files, matching inference BYTE-FOR-BYTE.

Renders each labeled example (`data/finetune/seed.jsonl`) through the SAME chat template + tool schema the local
model uses at inference (see llm_local.decide), so the fine-tune learns the exact `<tool_call>{...}</tool_call>`
target — not a lookalike. Writes `data/finetune/{train,valid}.jsonl` in mlx_lm's prompt/completion format
(the prompt is masked; loss is on the completion only).

Run:  uv run python scripts/build_dataset.py && uv run python scripts/format_for_mlx.py
Then: bash scripts/train_mlx.sh
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
SEED = ROOT / "data" / "finetune" / "seed.jsonl"
OUTDIR = ROOT / "data" / "finetune"


def main():
    from transformers import AutoTokenizer
    from sheru import config
    from sheru.tools import TOOLS
    from sheru.llm_local import SYSTEM

    if not SEED.exists():
        sys.exit("no seed.jsonl — run scripts/build_dataset.py first")
    tok = AutoTokenizer.from_pretrained(config.LOCAL_LLM)
    sysc = SYSTEM + config.reply_directive()
    rows = [json.loads(l) for l in SEED.read_text().splitlines() if l.strip()]

    out = []
    for r in rows:
        msgs = [{"role": "system", "content": sysc}, {"role": "user", "content": r["utterance"]}]
        prompt = tok.apply_chat_template(msgs, tools=TOOLS, add_generation_prompt=True, tokenize=False)
        if r.get("tool"):
            call = {"name": r["tool"], "arguments": r.get("arguments") or {}}
            completion = "<tool_call>\n" + json.dumps(call, ensure_ascii=False) + "\n</tool_call>"
        else:                                              # spoken-answer negative
            completion = (r.get("arguments") or {}).get("say") or "Sure."
        out.append({"prompt": prompt, "completion": completion})

    out.sort(key=lambda d: hash(d["prompt"]) & 0xFFFFFF)   # deterministic shuffle before the split
    k = max(1, len(out) // 10)
    valid, train = out[:k], out[k:]
    (OUTDIR / "train.jsonl").write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in train) + "\n")
    (OUTDIR / "valid.jsonl").write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in valid) + "\n")
    print(f"train={len(train)}  valid={len(valid)}  ->  data/finetune/{{train,valid}}.jsonl")
    print("example completion:", out[0]["completion"].replace("\n", " "))


if __name__ == "__main__":
    main()
