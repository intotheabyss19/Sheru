"""Speech-to-text.

Three backends (SHERU_STT):
- "parakeet" (default): parakeet-mlx, fast, but English/European only — it MANGLES Hindi (the #1 source of
  wrong songs/names in real use: "Sunya song by Kalashkir" -> "Sienna by The Marías").
- "whisper": mlx-whisper large-v3-turbo, auto-detects language so it handles Hindi + English + Hinglish
  code-switching. Slower (~0.5-1.5s) but correct for a Hindi/English user. Set SHERU_STT=whisper to enable.
- "sarvam": Saaras v3 in the cloud — trained on 22 Indian languages, best Hindi/Hinglish accuracy available.
  Needs network + config.SARVAM_API_KEY; falls back to config.SARVAM_STT_FALLBACK (whisper) whenever the call
  can't happen, so a dead network degrades the transcript instead of deafening Sheru.
"""
from __future__ import annotations

import logging
import os
import re
import time

import numpy as np

from . import config

_log = logging.getLogger("sheru.stt")


def _hallucinated(r: dict) -> bool:
    """True if a Whisper result is a silence/noise hallucination rather than real speech — so it can be dropped
    before it drives an action or (worse) arms a follow-up and loops.

    The reliable tell is a very high compression_ratio: on near-silence Whisper emits repeated filler
    ('I'm sorry. I'm sorry. …', 'I'm a …'), which gzip-compresses far better than real speech. This is
    Whisper's own anti-hallucination heuristic (threshold 2.4), which mlx-whisper doesn't enforce. On
    AGC-boosted hiss no_speech_prob/avg_logprob are unreliable (the model is falsely confident), so
    compression_ratio is primary; the logprob/no-speech bounds only catch the rare non-repetitive case."""
    segs = r.get("segments") or []
    if not segs:
        return False
    comp = max((s.get("compression_ratio", 0.0) or 0.0) for s in segs)
    lp = min((s.get("avg_logprob", 0.0) or 0.0) for s in segs)
    nsp = max((s.get("no_speech_prob", 0.0) or 0.0) for s in segs)
    # compression_ratio is the RELIABLE tell (repeated filler). avg_logprob/no_speech alone false-positive on real
    # but imperfect speech (a quiet or accented utterance scores low but is genuine — dropping it eats real commands),
    # so only treat them as a hallucination when BOTH are bad AND the text isn't clearly varied speech.
    return comp > 2.4 or (lp < -1.3 and nsp > 0.85)


def _collapse_repeats(text: str) -> str:
    """Whisper/Parakeet hallucinate on real-mic audio by repeating a phrase many times in a row
    ('This guy Uber not a guy' ×9). Collapse any immediately-repeated 1–6-word unit that recurs
    3+ times down to a single occurrence, then squash a doubled word ('closing closing' -> 'closing').
    Genuine speech almost never repeats a phrase verbatim, so this only fires on the degenerate loops."""
    words = text.split()
    if len(words) < 4:
        return text
    out, i, changed = [], 0, False
    while i < len(words):
        best = None
        for n in range(min(6, (len(words) - i) // 2), 0, -1):
            unit = words[i:i + n]
            reps, j = 1, i + n
            while words[j:j + n] == unit:
                reps += 1
                j += n
            if reps >= 3:
                best = (unit, j)
                break
        if best:
            out.extend(best[0])
            i = best[1]
            changed = True
        else:
            out.append(words[i])
            i += 1
    dedup = []                                      # doubled word ('closing closing' -> 'closing')
    for w in out:
        if dedup and dedup[-1].lower().strip(".,!?") == w.lower().strip(".,!?"):
            changed = True
            continue
        dedup.append(w)
    return " ".join(dedup) if changed else text


def _wav_bytes(audio: np.ndarray) -> bytes:
    """float32 mono @ 16 kHz -> a 16-bit PCM WAV in memory (what the Saaras endpoint wants to be handed)."""
    import io
    import wave
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


class Transcriber:
    def __init__(self, backend: str | None = None) -> None:
        self.backend = backend or config.STT_BACKEND
        self._model = None
        self._sarvam = None                   # lazily-built SarvamAI client (backend == "sarvam")
        self._fallback: "Transcriber | None" = None   # local backend used when the cloud call can't happen
        self.last_latency = 0.0

    def load(self) -> "Transcriber":
        if self.backend == "sarvam":
            return self                      # nothing to load: the model runs on Sarvam's side
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
        if self.backend == "sarvam":
            t0 = time.perf_counter()
            text = self._transcribe_sarvam(audio)
            if text is not None:
                self.last_latency = time.perf_counter() - t0
                return _collapse_repeats(text.strip())
            return self._local_fallback().transcribe(audio)   # offline / no key / clip too long
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
                        no_speech_threshold=0.6, logprob_threshold=-1.0, task="transcribe",   # transcribe, never translate
                        initial_prompt="यह हिंदी और अंग्रेज़ी में बातचीत है। A conversation in Hindi and English "
                                       "(Hinglish); keep Hindi words in Devanagari, do not translate.")
            def _do():
                if forced:
                    return mlx_whisper.transcribe(audio, language=forced, **opts)
                r = mlx_whisper.transcribe(audio, **opts)                    # auto-detect...
                if r.get("language") not in ("en", "hi"):                    # ...clamp: never accept Russian/other on Hindi or noise
                    r = mlx_whisper.transcribe(audio, language="en", **opts)
                return r
            r = mlx_pool.run(_do)
            text = r.get("text", "")
            if text.strip() and _hallucinated(r):        # drop silence/noise hallucinations before they act or loop
                _log.info("stt dropped hallucination %r (comp_ratio=%.1f)", text.strip()[:40],
                          max((s.get("compression_ratio", 0.0) or 0.0) for s in (r.get("segments") or [{}])))
                text = ""
        else:
            import mlx.core as mx
            from parakeet_mlx.audio import get_logmel
            def _do():
                mel = get_logmel(mx.array(audio.astype(np.float32)), self._model.preprocessor_config)
                return self._model.generate(mel)[0].text
            text = mlx_pool.run(_do)
        self.last_latency = time.perf_counter() - t0
        return _collapse_repeats(text.strip())

    def _local_fallback(self) -> "Transcriber":
        if self._fallback is None:
            self._fallback = Transcriber(config.SARVAM_STT_FALLBACK)
        return self._fallback

    def _ensure_sarvam(self):
        if self._sarvam is None:
            from sarvamai import SarvamAI
            self._sarvam = SarvamAI(api_subscription_key=config.SARVAM_API_KEY, timeout=config.SARVAM_TIMEOUT)
        return self._sarvam

    def _transcribe_sarvam(self, audio: np.ndarray) -> str | None:
        """Saaras v3 over the network. Returns the transcript ("" is a valid answer — silence), or None when
        the call could not be made or failed, which is the caller's signal to use the local backend."""
        if not config.SARVAM_API_KEY:
            return None
        if audio.size / config.SAMPLE_RATE > config.SARVAM_STT_MAX_SECONDS:
            return None
        try:
            from . import net
            if not net.online("api.sarvam.ai"):
                return None
            r = self._ensure_sarvam().speech_to_text.transcribe(
                file=("audio.wav", _wav_bytes(audio), "audio/wav"),
                model=config.SARVAM_STT_MODEL,
                mode="transcribe",                 # keep the user's own language; "translate" would force English
            )
            return r.transcript or ""
        except Exception:
            return None
