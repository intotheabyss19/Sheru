# Local LoRA fine-tune — result (2026-08-30)

**Outcome: base model kept; adapter NOT deployed.** The eval-gate rejected it — the correct, expected result
for a first pass on a tiny synthetic dataset.

## What ran
- `mlx_lm.lora` on `mlx-community/Qwen3-4B-4bit`, 8 LoRA layers, seq 2048, LR 1e-4, batch 1, grad-checkpoint.
- Data: 242 train / 26 val examples (synthetic seed + a little Claude-distilled), rendered byte-for-byte
  through the inference chat template (`scripts/format_for_mlx.py`).
- Stopped at iter 200 (~1.7 epochs): **val loss 2.32 → 0.012, plateaued by iter 100** (train loss ~0.01 —
  the model memorized the small, repetitive completion space fast). Checkpoints saved at 100 and 200.

## The gate (`scripts/eval_router.py`)
A held-out battery of realistic + broken-English utterances, scored on tool-choice accuracy, with a
chat-negatives check. **Deploy only if the adapter strictly beats base with no chat regression.**

| model | overall | chat-neg | notes |
|---|---|---|---|
| **base** | 30/38 (79%) | 6/6 | errs conservative ("says" instead of acting — Tier-0 grammar catches those anyway); **all search/look_up cases correct** |
| adapter iter100 | 32/38 (84%) | 5/6 ❌ | regressed a chat-negative; confused tools (open spotify→play_song, pause→web_search) |
| adapter iter200 | 31/38 (82%) | 6/6 | **broke local-first** (sent 4 search queries to Claude); hallucinated a nonexistent `create_folder` tool |

## Why base wins
Neither adapter strictly beats base on what matters: iter100 regresses chat-negatives and makes *executable*
tool-confusion errors; iter200 defeats the whole point (search must stay local) and invents a tool. The overfit
adapter generalizes worse on novel phrasings than the base + wide Tier-0 grammar already do.

## To make fine-tuning actually help later
Bigger, REAL dataset (distill Claude on logged utterances, not synthetic seed), include the newer tools
(`look_up`, `play_youtube`), add hard negatives + ~30-50% general chat, stronger regularization (lower LR /
fewer layers / more dropout), and re-run the same gate. Adapter files are under `data/finetune/` (gitignored).
