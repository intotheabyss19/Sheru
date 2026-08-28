"""Dev-mode data capture: save every voice clip (raw audio WAV) + its parakeet transcription.

Everything lands in data/ (gitignored — never published). Paired index at data/recordings.jsonl. Turn off
later with SHERU_RECORD=0 (privacy). Complements data/journal.jsonl (which logs every input + routing).
"""
from __future__ import annotations

import json
import os
import time

import numpy as np
import soundfile as sf

from . import config

REC_DIR = config.DATA_DIR / "recordings"
INDEX = config.DATA_DIR / "recordings.jsonl"


_override = None   # runtime toggle via voice ("stop recording")

def set_enabled(on: bool) -> None:
    global _override
    _override = on

def enabled() -> bool:
    if _override is not None:
        return _override
    return os.environ.get("SHERU_RECORD", "1") == "1"   # ON by default during development


def save(audio: "np.ndarray", transcript: str, stt_latency: float = 0.0, kind: str = "voice",
         routed: str | None = None) -> str | None:
    """Save one raw audio clip + its transcription; append a paired record. Returns the wav path."""
    if not enabled() or audio is None or getattr(audio, "size", 0) == 0:
        return None
    REC_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    wav = REC_DIR / f"{stamp}.wav"
    sf.write(str(wav), audio.astype(np.float32), config.SAMPLE_RATE)
    rec = {
        "ts": round(time.time(), 3),
        "file": str(wav.relative_to(config.DATA_DIR)),
        "transcript": transcript,
        "rms": round(float(np.sqrt((audio ** 2).mean())), 4),
        "duration_s": round(audio.size / config.SAMPLE_RATE, 2),
        "stt_latency": round(stt_latency, 3),
        "kind": kind,
        "routed": routed,
    }
    with open(INDEX, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return str(wav)
