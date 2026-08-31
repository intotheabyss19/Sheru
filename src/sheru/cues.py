"""Assistant-style cue tones — clean, very-high sine-wave blips (like Google Assistant / Siri), generated on the
fly instead of the percussive macOS system sounds (Pop/Tink), which don't pitch up cleanly.

Two distinct cues, unmistakable eyes-free:
  * listen ("your turn to speak")  — a RISING two-tone
  * speak  ("Sheru is replying")   — a FALLING two-tone

Written to data/cues/*.wav once at startup; play with afplay. Tune the frequencies in CUES below.
"""
from __future__ import annotations

import numpy as np

from . import config

_SR = 44100
_DIR = config.DATA_DIR / "cues"

# Cue THEMES the user can pick in Settings. Each = (listen freqs, speak freqs) in Hz.
# Rising = "your turn to speak", falling = "Sheru is replying".
PRESETS = {
    "chime":      ([1568, 2093], [2093, 1568]),   # G6→C7 / C7→G6 — bright (default)
    "chime_high": ([2093, 2793], [2793, 2093]),   # C7→F7 / F7→C7 — very high / piercing
    "soft":       ([880, 1174],  [1174, 880]),    # A5→D6 / D6→A5 — gentler, lower
    "classic":    ([1200, 1600], [1600, 1200]),   # plain mid two-tone
}


def _current() -> tuple[list[int], list[int]]:
    from . import config
    return PRESETS.get(config.CUE_STYLE, PRESETS["chime"])


def _tone(freqs: list[int], dur: float = 0.085, gap: float = 0.012, gain: float = 0.6) -> np.ndarray:
    """A sequence of pure sine notes with click-free attack/release envelopes."""
    a = max(1, int(_SR * 0.006))          # 6 ms attack
    rel = max(1, int(_SR * 0.030))        # 30 ms release
    parts = []
    for i, f in enumerate(freqs):
        n = int(_SR * dur)
        t = np.arange(n) / _SR
        env = np.ones(n, dtype=np.float32)
        env[:a] = np.linspace(0.0, 1.0, a)
        env[-rel:] *= np.linspace(1.0, 0.0, rel)
        parts.append((np.sin(2 * np.pi * f * t) * env * gain).astype(np.float32))
        if gap and i < len(freqs) - 1:
            parts.append(np.zeros(int(_SR * gap), dtype=np.float32))
    return np.concatenate(parts)


def ensure_cues() -> dict[str, str]:
    """(Re)generate the cue WAVs for the current theme (config.CUE_STYLE) and return {name: path}. Overwrites each
    call so a theme change from Settings takes effect immediately."""
    import soundfile as sf
    _DIR.mkdir(parents=True, exist_ok=True)
    listen_f, speak_f = _current()
    paths = {}
    for name, freqs in (("listen", listen_f), ("speak", speak_f)):
        p = _DIR / f"{name}.wav"
        try:
            sf.write(str(p), _tone(freqs), _SR)
        except Exception:
            pass
        paths[name] = str(p)
    return paths
