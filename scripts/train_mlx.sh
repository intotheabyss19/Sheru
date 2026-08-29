#!/usr/bin/env bash
# Phase 4 — LoRA fine-tune Sheru's local router on the formatted dataset (Apple MLX, ~20-40 min on an M-series).
# Prereqs:  uv run python scripts/build_dataset.py && uv run python scripts/format_for_mlx.py
# The adapter lands under data/ (gitignored). Fuse it into a servable model at the end, or point the app at the
# adapter via mlx_lm's --adapter-path. Data (train/valid.jsonl) is prompt/completion; loss is on the completion.
set -euo pipefail
cd "$(dirname "$0")/.."

MODEL="${SHERU_LLM:-mlx-community/Qwen3-4B-4bit}"
DATA="data/finetune"
ADAPTER="data/finetune/adapter"
mkdir -p "$ADAPTER"

echo "Fine-tuning $MODEL on $DATA  (iters=${ITERS:-300}, batch=${BATCH:-4}, layers=${LAYERS:-8})"
uv run python -m mlx_lm.lora \
  --model "$MODEL" \
  --train \
  --data "$DATA" \
  --iters "${ITERS:-300}" \
  --batch-size "${BATCH:-4}" \
  --num-layers "${LAYERS:-8}" \
  --learning-rate 1e-4 \
  --adapter-path "$ADAPTER"

echo
echo "Done. Adapter -> $ADAPTER"
echo "Fuse into a servable model:"
echo "  uv run python -m mlx_lm.fuse --model $MODEL --adapter-path $ADAPTER --save-path data/finetune/sheru-4b-tuned"
echo "Then point Sheru at it:  SHERU_LLM=\$(pwd)/data/finetune/sheru-4b-tuned uv run sheru"
