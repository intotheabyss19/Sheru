#!/usr/bin/env bash
# Phase 4 — LoRA fine-tune Sheru's local router on the formatted dataset (Apple MLX, ~20-40 min on an M-series).
# Prereqs:  uv run python scripts/build_dataset.py && uv run python scripts/format_for_mlx.py
#
# MEMORY (16 GB): training the 4B OOMs if the Sheru app is running (it holds the 4B + Whisper + Kokoro resident).
# STOP THE APP FIRST:  pkill -f '.venv/bin/sheru'   (restart it after). Defaults below are 16 GB-safe (batch 1,
# 4 LoRA layers, gradient checkpointing, short sequences). For a bigger/faster run use RunPod (see docs/finetuning-
# research.md) — rotate the exposed RunPod key first. The adapter lands under data/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."

if pgrep -f '.venv/bin/sheru' >/dev/null; then
  echo "⚠️  The Sheru app is running — training will likely OOM on 16 GB."
  echo "    Stop it first:  pkill -f '.venv/bin/sheru'   (then re-run this)."
  [ "${FORCE:-0}" = "1" ] || exit 1
fi

MODEL="${SHERU_LLM:-mlx-community/Qwen3-4B-Instruct-2507-4bit}"
DATA="data/finetune"
ADAPTER="data/finetune/adapter"
mkdir -p "$ADAPTER"

echo "Fine-tuning $MODEL on $DATA  (iters=${ITERS:-400}, batch=${BATCH:-1}, layers=${LAYERS:-8}, seq=${SEQ:-2048})"
uv run python -m mlx_lm.lora \
  --model "$MODEL" \
  --train \
  --data "$DATA" \
  --iters "${ITERS:-400}" \
  --batch-size "${BATCH:-1}" \
  --num-layers "${LAYERS:-8}" \
  --max-seq-length "${SEQ:-2048}" \
  --grad-checkpoint \
  --learning-rate "${LR:-1e-4}" \
  --steps-per-report 20 \
  --steps-per-eval 50 \
  --val-batches 12 \
  --save-every "${SAVE_EVERY:-100}" \
  --adapter-path "$ADAPTER"

echo
echo "Done. Adapter -> $ADAPTER"
echo "Fuse into a servable model:"
echo "  uv run python -m mlx_lm.fuse --model $MODEL --adapter-path $ADAPTER --save-path data/finetune/sheru-4b-tuned"
echo "Then point Sheru at it:  SHERU_LLM=\$(pwd)/data/finetune/sheru-4b-tuned uv run sheru"
