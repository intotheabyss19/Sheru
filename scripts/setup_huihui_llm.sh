#!/bin/sh
# Convert huihui's abliterated Qwen3-4B-Instruct-2507 to a local MLX 4-bit model and point Sheru at it.
# On our router eval it scored 95% (36/38) vs the stock mlx-community 2507-4bit's 76% (29/38) — a much better
# router AND far less refusal-prone. The converted weights + the profile pointer live in data/ (gitignored),
# so a fresh clone recreates them with this script. (Revert: set profile llm_model back to the config default.)
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/data/models/huihui-qwen3-4b-2507-ablit-4bit"
echo "Downloading + converting huihui-ai/Huihui-Qwen3-4B-Instruct-2507-abliterated -> $OUT"
PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" - <<PY
from huggingface_hub import snapshot_download
snapshot_download('huihui-ai/Huihui-Qwen3-4B-Instruct-2507-abliterated')   # full snapshot (avoids the save bug)
from mlx_lm import convert
convert(hf_path='huihui-ai/Huihui-Qwen3-4B-Instruct-2507-abliterated', mlx_path='$OUT', quantize=True, q_bits=4)
from sheru import config
config.update_profile('llm_model', '$OUT')
print('Done. Sheru now routes with', '$OUT')
PY
