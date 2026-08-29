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
LOCAL_LLM = os.environ.get("SHERU_LLM") or _P.get("llm_model") or "mlx-community/Qwen3-4B-4bit"   # resident tier. 4B routes as well as 8B (verified) and is snappier; set profile 'llm_model' or SHERU_LLM=mlx-community/Qwen3-8B-4bit for warmer chit-chat
LOCAL_LLM_FAST = os.environ.get("SHERU_LLM_FAST") or None                       # optional light tier; set to e.g. mlx-community/Qwen3-4B-4bit
# STT backend: "parakeet" (fast, English/European only), "whisper" (Hindi + English + Hinglish, slower, local),
# or "sarvam" (Saaras v3 in the cloud — best Hindi/Hinglish by a wide margin, needs network + an API key).
# Real Hindi NEEDS whisper or sarvam — parakeet mangles it into garbage.
# Set profile 'stt_backend' or SHERU_STT=sarvam.
STT_BACKEND = os.environ.get("SHERU_STT") or _P.get("stt_backend") or "parakeet"
# Force Whisper to a language ("en"/"hi") instead of auto-detect; None = auto-detect but CLAMPED to en/hi
# (Parakeet-v3 and Whisper both hallucinate Russian/other Cyrillic on Hindi speech or noise — the clamp kills that).
STT_LANG = os.environ.get("SHERU_STT_LANG") or _P.get("stt_lang") or None

# Microphone input device: a device index (as a string) or a name substring; None/"" = AUTO-pick the built-in
# MacBook mic (best voice isolation + noise rejection). Set profile 'mic_device' (via the menu-bar picker) or SHERU_MIC.
MIC_DEVICE = os.environ.get("SHERU_MIC") or _P.get("mic_device") or None


def _claude_config_dir() -> str | None:
    """Which Claude login Tier-2 (`claude -p`) uses. The GUI/login-item launch inherits an EMPTY
    CLAUDE_CONFIG_DIR and silently falls back to ~/.claude — which may be a different org with Claude Code
    DISABLED, so every escalation fails and Sheru drops to the dumb local answer. Pin it to the real login.
    Override with SHERU_CLAUDE_CONFIG_DIR or profile 'claude_config_dir'; else auto-detect ~/.claude-ashish."""
    v = os.environ.get("SHERU_CLAUDE_CONFIG_DIR") or _P.get("claude_config_dir")
    if v:
        return str(Path(v).expanduser())
    cand = Path.home() / ".claude-ashish"
    return str(cand) if cand.is_dir() else None


CLAUDE_CONFIG_DIR = _claude_config_dir()

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
TTS_PITCH = float(os.environ.get("SHERU_PITCH", "1.0"))          # 1.0 = normal. >1.15 up-pitches but WARBLES on AVSpeech (the "wobble"); leave at 1.0 for a clean male voice
TTS_RATE = float(os.environ.get("SHERU_RATE", "0.5"))
TTS_PREFERRED = ("Rishi", "Daniel", "Fred", "Aaron", "Tom")     # male, best-quality match wins (Rishi = enhanced Indian-English, installed)
NAME_SPOKEN = "Sheroo"                                           # how Sheru pronounces its own name

# TTS engine: "avspeech" (built-in, instant) or "kokoro" (mlx-audio Kokoro-82M — natural neural voice). Kokoro
# needs `mlx-audio` + `misaki[en]` and a one-time spaCy `en_core_web_sm` fetch (do it on a clean network, not the
# Sophos wifi which resets runtime downloads). Falls back to AVSpeech automatically on any failure/NaN.
# Set profile 'tts_backend' or SHERU_TTS=kokoro.
TTS_BACKEND = os.environ.get("SHERU_TTS") or _P.get("tts_backend") or "avspeech"
KOKORO_MODEL = os.environ.get("SHERU_KOKORO", "mlx-community/Kokoro-82M-bf16")
KOKORO_VOICE = os.environ.get("SHERU_KOKORO_VOICE") or _P.get("kokoro_voice") or "am_michael"   # male US; Hindi: hm_omega / hf_alpha
KOKORO_SPEED = float(os.environ.get("SHERU_KOKORO_SPEED", "1.0"))

# Sarvam (cloud) TTS: Bulbul v3 — real Indian-language voices, 11 languages. Needs network + a key from
# dashboard.sarvam.ai. Set SHERU_TTS=sarvam. Put the key in data/profile.json as 'sarvam_api_key': the
# menu-bar / login-item launch does NOT inherit your shell env, so SARVAM_API_KEY only works from a terminal.
# Any failure (offline, bad key, 429, text too long) falls back to AVSpeech, so Sheru never goes mute.
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY") or _P.get("sarvam_api_key") or None
SARVAM_VOICE = os.environ.get("SHERU_SARVAM_VOICE") or _P.get("sarvam_voice") or "shubh"   # young male. female: ishita
SARVAM_LANG = os.environ.get("SHERU_SARVAM_LANG") or _P.get("sarvam_lang") or "auto"       # "auto" | hi-IN | en-IN | ...
SARVAM_PACE = float(os.environ.get("SHERU_SARVAM_PACE", "1.0"))       # 0.5-2.0 on bulbul:v3
SARVAM_TIMEOUT = float(os.environ.get("SHERU_SARVAM_TIMEOUT", "8"))   # give up and use AVSpeech after this
SARVAM_MAX_CHARS = 2500                                               # bulbul:v3 hard cap on one request
SARVAM_STT_MODEL = os.environ.get("SHERU_SARVAM_STT") or "saaras:v3"
SARVAM_STT_MAX_SECONDS = 30.0    # sync REST cap; longer clips go to the local backend instead of erroring
# Local backend used when the Saaras call can't happen (offline / no key / clip too long). whisper, not
# parakeet: the whole point of running sarvam is Hindi, and parakeet cannot do Hindi at all.
SARVAM_STT_FALLBACK = os.environ.get("SHERU_SARVAM_STT_FALLBACK") or _P.get("sarvam_stt_fallback") or "whisper"


# What language Sheru answers in. "auto" mirrors whatever the user spoke, "hi" pins Hindi, "en" is the old
# English-only behaviour. A Hindi VOICE does not make Hindi REPLIES — the model has to be told.
REPLY_LANG = os.environ.get("SHERU_REPLY_LANG") or _P.get("reply_lang") or "auto"

def reply_directive(text: str = "") -> str:
    """Appended to every system prompt so the reply language matches what the user spoke. In 'auto' mode we PIN
    the language by the INPUT'S SCRIPT here in code (deterministic) rather than asking the small local model to
    evaluate 'reply in their language' — which it fails, answering English questions in Hindi."""
    if REPLY_LANG == "hi":
        return " Always reply in Hindi, using Devanagari script, however the user phrased the question."
    if REPLY_LANG == "en":
        return " Reply in English."
    if text and any("ऀ" <= c <= "ॿ" for c in text):     # the user's message contains Devanagari
        return " The user spoke Hindi — reply in Hindi using Devanagari script."
    return " The user spoke English — reply ONLY in English. Do not use Hindi or Devanagari."


def set_tts(backend: str) -> None:
    """Switch the TTS engine at runtime (avspeech|kokoro|sarvam) and persist it — the Speaker reads it per call."""
    global TTS_BACKEND
    TTS_BACKEND = backend
    update_profile("tts_backend", backend)


def set_reply_lang(lang: str) -> None:
    """Switch reply language at runtime (auto|hi|en) and persist it — reply_directive() reads it per call."""
    global REPLY_LANG
    REPLY_LANG = lang
    update_profile("reply_lang", lang)


def set_mic(device) -> None:
    """Choose the input device (index or name substring; None = auto built-in) and persist it. Takes effect on the
    next listen (the push-to-talk mic opens per-call; the always-on Listener re-reads it when restarted)."""
    global MIC_DEVICE
    MIC_DEVICE = device
    update_profile("mic_device", device)


def sarvam_lang_for(text: str) -> str:
    """Bulbul needs an explicit language_code — it has no auto-detect. "auto" means: Devanagari in the reply
    -> hi-IN, otherwise en-IN (Indian-accented English), so a Hinglish assistant doesn't read plain English
    through a Hindi language model."""
    if SARVAM_LANG != "auto":
        return SARVAM_LANG
    return "hi-IN" if any("\u0900" <= c <= "\u097f" for c in text) else "en-IN"

