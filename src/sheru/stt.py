"""Speech-to-text on-device. Backend: parakeet-mlx (English), fed numpy audio directly (no ffmpeg, no temp files)."""
from __future__ import annotations

import os
import time

import numpy as np

from . import config


class Transcriber:
    def __init__(self, backend: str | None = None) -> None:
        self.backend = backend or os.environ.get("SHERU_STT", "parakeet")
        self._model = None
        self.last_latency = 0.0

    def load(self) -> "Transcriber":
        if self._model is None:
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
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel
        self.load()
        from . import mlx_pool
        t0 = time.perf_counter()
        def _do():
            mel = get_logmel(mx.array(audio.astype(np.float32)), self._model.preprocessor_config)
            return self._model.generate(mel)[0].text
        text = mlx_pool.run(_do)
        self.last_latency = time.perf_counter() - t0
        return text.strip()
