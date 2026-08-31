"""Screen understanding via the local huihui Qwen3-VL-4B-abliterated model (MLX).

mlx-vlm's dependencies conflict with Sheru's runtime, so the model runs in a DURABLE isolated venv
(data/vlm-venv) that Sheru shells out to: screencapture → VLM → a natural-language answer about the screen.
Everything stays on-device (the screenshot never leaves the machine). Falls back to Apple Vision OCR
(actions/screen.py) whenever the venv/model isn't available or errors.

Note: each call reloads the model in a fresh subprocess (~several seconds). Fine for on-demand
"what's on my screen"; a persistent VLM server is a future optimization.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

from . import config

_log = logging.getLogger("sheru.vision")

_DEFAULT_Q = ("Describe what is on this screen for a voice assistant, in 2-4 sentences. "
              "Mention the app/window, the key text, and any important buttons or fields.")


def available() -> bool:
    """True if the local VLM can be used (enabled + the isolated venv exists)."""
    return bool(config.VLM_ENABLED) and os.path.exists(config.VLM_PYTHON)


def _clean(stdout: str) -> str:
    """Keep the model's answer, drop mlx_vlm.generate's stats/progress lines, and strip markdown so TTS doesn't
    read '**' / '#' aloud."""
    import re
    out = []
    for ln in (stdout or "").splitlines():
        s = ln.strip()
        if (not s or s.startswith("=") or s.startswith("Prompt:") or s.startswith("Files:")
                or s.startswith("Generation") or s.startswith("Peak memory") or "tokens-per-sec" in s
                or "Fetching" in s or "it/s]" in s):
            continue
        out.append(ln)
    text = "\n".join(out).strip()
    text = re.sub(r"\*\*|\*|`|^#+\s*", "", text, flags=re.M)   # drop markdown bold/italic/code/headers
    return text.strip()


def describe_screen(question: str | None = None, timeout: float = 120.0) -> str | None:
    """Screenshot the screen and ask the local VLM about it. `question` steers it ("what's on my screen",
    "what's the error", "what should I click to send"). Returns the answer, or None on any failure so the
    caller can fall back to OCR."""
    if not available():
        return None
    q = (question or "").strip() or _DEFAULT_Q
    img = tempfile.mktemp(suffix=".png")
    try:
        cap = subprocess.run(["screencapture", "-x", img], timeout=15)
        if cap.returncode != 0 or not os.path.exists(img):
            _log.info("vision: screencapture failed (Screen Recording permission?)")
            return None
        r = subprocess.run(
            [config.VLM_PYTHON, "-m", "mlx_vlm.generate", "--model", config.VLM_MODEL,
             "--image", img, "--prompt", q, "--max-tokens", "220", "--temperature", "0.0"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            env={**os.environ, "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE", "0")})
        text = _clean(r.stdout)
        if not text:
            _log.info("vision: empty VLM output; stderr=%r", (r.stderr or "").strip()[-200:])
            return None
        _log.info("vision: described screen (%d chars)", len(text))
        return text
    except subprocess.TimeoutExpired:
        _log.info("vision: VLM timed out after %.0fs", timeout)
        return None
    except Exception as e:
        _log.info("vision: describe_screen failed: %s", e)
        return None
    finally:
        try:
            os.remove(img)
        except OSError:
            pass
