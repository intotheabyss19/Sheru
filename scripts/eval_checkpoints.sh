#!/usr/bin/env bash
# Eval-gate helper: score BASE + every saved LoRA checkpoint + the final adapter on the held-out battery
# (scripts/eval_router.py). Each run is a FRESH subprocess so the ~2.5 GB model is freed between checkpoints
# (loading them all in one process would OOM 16 GB). Prints "SCORE ok n chat_ok chat_n" per row.
#
# Deploy rule: pick the checkpoint with the highest overall that STRICTLY beats BASE and keeps chat_ok == chat_n
# (no chit-chat regression). If none qualifies, KEEP BASE.  Run:  bash scripts/eval_checkpoints.sh
set -uo pipefail
cd "$(dirname "$0")/.."
ADIR=data/finetune/adapter
row() { printf "%-26s %s\n" "$1" "$2"; }

echo "=== eval-gate: BASE vs LoRA checkpoints (held-out battery) ==="
printf "%-26s %s\n" "checkpoint" "SCORE ok n chat_ok chat_n"
S=$(HF_HUB_OFFLINE=1 .venv/bin/python scripts/eval_router.py 2>/dev/null | grep '^SCORE')
row "BASE" "$S"

for c in "$ADIR"/*_adapters.safetensors; do
  [ -e "$c" ] || continue
  T=$(mktemp -d)
  cp "$ADIR/adapter_config.json" "$T/" 2>/dev/null || true
  cp "$c" "$T/adapters.safetensors"
  S=$(HF_HUB_OFFLINE=1 .venv/bin/python scripts/eval_router.py --adapter "$T" 2>/dev/null | grep '^SCORE')
  row "$(basename "$c" .safetensors)" "$S"
  rm -rf "$T"
done

if [ -e "$ADIR/adapters.safetensors" ]; then
  S=$(HF_HUB_OFFLINE=1 .venv/bin/python scripts/eval_router.py --adapter "$ADIR" 2>/dev/null | grep '^SCORE')
  row "final" "$S"
fi
echo "=== done. Deploy a checkpoint ONLY if it strictly beats BASE overall with chat_ok==chat_n. ==="
