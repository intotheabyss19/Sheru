"""Paths and user-tunable settings for Sheru."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Models are pre-downloaded; never block startup on huggingface.co (also avoids SSL-intercept noise).
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
MODELS = Path(os.environ.get("SHERU_MODELS", ROOT / "models"))
KWS_DIR = MODELS / "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
KEYWORDS_FILE = MODELS / "keywords.txt"
VAD_MODEL = MODELS / "silero_vad.onnx"
DATA_DIR = Path(os.environ.get("SHERU_DATA", ROOT / "data"))   # journal, memory, datasets (gitignored)

def _profile() -> dict:
    import json
    f = DATA_DIR / "profile.json"
    try:
        return json.loads(f.read_text())
    except Exception:
        return {}

_P = _profile()
USER_NAME = os.environ.get("SHERU_USER") or _P.get("name") or "you"   # personal name stays in data/profile.json


def update_profile(key: str, value) -> None:
    import json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / "profile.json"
    try:
        d = json.loads(f.read_text())
    except Exception:
        d = {}
    d[key] = value
    f.write_text(json.dumps(d, indent=2))
    _P[key] = value

SAMPLE_RATE = 16_000
WAKE_WORDS = ("hey sheru", "sheru")
LOCAL_LLM = os.environ.get("SHERU_LLM", "mlx-community/Qwen3-4B-4bit")          # resident tier (4B: lighter/faster on 16GB; set SHERU_LLM=mlx-community/Qwen3-8B-4bit for 8B)
LOCAL_LLM_FAST = os.environ.get("SHERU_LLM_FAST") or None                       # optional light tier; set to e.g. mlx-community/Qwen3-4B-4bit

# Browser / search preferences (mutable at runtime by voice: "use google")
BROWSER_APP = "Zen"
ZEN_PROFILES_INI = Path.home() / "Library/Application Support/zen/profiles.ini"
SEARCH_ENGINES = {
    "google": "https://www.google.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
}
IMAGE_SEARCH = {
    "google": "https://www.google.com/search?tbm=isch&q={q}",
    "duckduckgo": "https://duckduckgo.com/?ia=images&iax=images&q={q}",
    "bing": "https://www.bing.com/images/search?q={q}",
}

# TTS: "smart teen boy" target. Prefer an Enhanced/Premium MALE voice, pitched up a little.
# Override with SHERU_VOICE (a voice name or identifier) and SHERU_PITCH (e.g. 1.25).
# Download better male voices in System Settings > Accessibility > Spoken Content > System Voice > Manage Voices
# (good picks: "Aaron (Enhanced)", any "Siri Voice" male, or "Rishi (Enhanced)" for Indian English).
TTS_VOICE = os.environ.get("SHERU_VOICE") or None
TTS_PITCH = float(os.environ.get("SHERU_PITCH", "1.22"))         # 1.0 = normal; ~1.2-1.35 reads younger
TTS_RATE = float(os.environ.get("SHERU_RATE", "0.52"))
TTS_PREFERRED = ("Aaron", "Rishi", "Tom", "Daniel", "Fred")     # male, best-quality match wins
NAME_SPOKEN = "Sheroo"                                           # how Sheru pronounces its own name
