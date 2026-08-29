"""Speech-to-text on-device.

Two backends (SHERU_STT):
- "parakeet" (default): parakeet-mlx, fast, but English/European only — it MANGLES Hindi (the #1 source of
  wrong songs/names in real use: "Sunya song by Kalashkir" -> "Sienna by The Marías").
- "whisper": mlx-whisper large-v3-turbo, auto-detects language so it handles Hindi + English + Hinglish
  code-switching. Slower (~0.5-1.5s) but correct for a Hindi/English user. Set SHERU_STT=whisper to enable.
"""
from __future__ import annotations

import os
import time

import numpy as np

from . import config


class Transcriber:
    def __init__(self, backend: str | None = None) -> None:
        self.backend = backend or config.STT_BACKEND
        self._model = None
        self.last_latency = 0.0

    def load(self) -> "Transcriber":
        if self._model is None:
            if self.backend == "whisper":
                self._model = "whisper"      # mlx-whisper loads + caches the model itself on first transcribe
            else:
                from parakeet_mlx import from_pretrained
                from . import mlx_pool
                self._model = mlx_pool.run(from_pretrained,
                                           os.environ.get("SHERU_PARAKEET", "mlx-community/parakeet-tdt-0.6b-v3"))
        return self

    def transcribe(self, audio: np.ndarray) -> str:
        """audio: float32 mono @ 16 kHz -> text ('' if nothing)."""
        if audio.size < config.SAMPLE_RATE // 10:
            return ""
        # auto-gain: boost quiet input (MacBook mic runs low) so STT doesn't garble it
        peak = float(np.abs(audio).max())
        if 0.002 < peak < 0.4:
            audio = np.clip(audio * (0.5 / peak), -1.0, 1.0).astype(np.float32)
        self.load()
        from . import mlx_pool
        t0 = time.perf_counter()
        if self.backend == "whisper":
            import mlx_whisper
            repo = os.environ.get("SHERU_WHISPER", "mlx-community/whisper-large-v3-turbo")
            audio = audio.astype(np.float32)
            forced = config.STT_LANG
            # anti-hallucination settings: single greedy temp, don't feed prior text (stops runaway loops),
            # bias vocabulary toward Hinglish. no_speech/logprob thresholds suppress transcribing silence.
            opts = dict(path_or_hf_repo=repo, temperature=0.0, condition_on_previous_text=False,
                        no_speech_threshold=0.6, logprob_threshold=-1.0,
                        initial_prompt="A conversation mixing Hindi and English (Hinglish).")
            def _do():
                if forced:
                    return mlx_whisper.transcribe(audio, language=forced, **opts).get("text", "")
                r = mlx_whisper.transcribe(audio, **opts)                    # auto-detect...
                if r.get("language") not in ("en", "hi"):                    # ...clamp: never accept Russian/other on Hindi or noise
                    r = mlx_whisper.transcribe(audio, language="en", **opts)
                return r.get("text", "")
            text = mlx_pool.run(_do)
        else:
            import mlx.core as mx
            from parakeet_mlx.audio import get_logmel
            def _do():
                mel = get_logmel(mx.array(audio.astype(np.float32)), self._model.preprocessor_config)
                return self._model.generate(mel)[0].text
            text = mlx_pool.run(_do)
        self.last_latency = time.perf_counter() - t0
        return text.strip()
