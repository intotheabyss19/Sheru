#!/bin/sh
# One-time setup for Sheru's screen-vision engine — huihui Qwen3-VL-4B-abliterated via mlx-vlm.
# mlx-vlm's dependencies conflict with Sheru's runtime, so it runs in a DURABLE isolated venv that Sheru
# shells out to (see src/sheru/vision.py). data/vlm-venv is gitignored, so recreate it with this script.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VLM="$ROOT/data/vlm-venv"
echo "Creating isolated vision venv at $VLM"
uv venv "$VLM" --python 3.12
uv pip install --python "$VLM/bin/python" mlx-vlm jinja2
"$VLM/bin/python" -c "import mlx_vlm; print('vlm venv ready:', mlx_vlm.__version__)"
echo "Done. Sheru uses it for 'what's on my screen'. Disable with SHERU_VISION=off."
