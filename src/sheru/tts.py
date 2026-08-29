"""Speech output. AVSpeechSynthesizer via pyobjc (<100 ms to first audio); `say` as fallback.

Optional neural backends (config.TTS_BACKEND): "kokoro" (local, English) and "sarvam" (cloud Bulbul v3,
real Hindi + 10 other Indian languages). Both degrade to AVSpeech on any failure."""
from __future__ import annotations

import subprocess
import threading

from . import config

try:  # pyobjc
    from AVFoundation import (
        AVSpeechSynthesisVoice,
        AVSpeechSynthesizer,
        AVSpeechUtterance,
        AVSpeechBoundaryImmediate,
    )
except Exception:  # pragma: no cover - non-mac or missing framework
    AVSpeechSynthesizer = None


def _pick_voice():
    voices = [v for v in AVSpeechSynthesisVoice.speechVoices() if str(v.language()).startswith("en")]
    if config.TTS_VOICE:                                   # explicit override by id or name
        for v in voices:
            if config.TTS_VOICE in (v.identifier(), v.name()):
                return v
    male = [v for v in voices if v.gender() == 1] or voices
    pref = {n: i for i, n in enumerate(config.TTS_PREFERRED)}
    # best quality first; then our preferred-name order; then anything male
    male.sort(key=lambda v: (v.quality(), -pref.get(v.name(), 99)), reverse=True)
    return male[0] if male else (voices[0] if voices else None)


class Speaker:
    """Thread-safe, interruptible speaker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._synth = AVSpeechSynthesizer.alloc().init() if AVSpeechSynthesizer else None
        self._voice = _pick_voice() if self._synth else None
        self._kokoro = None          # lazily-loaded Kokoro-82M model (when config.TTS_BACKEND == "kokoro")
        self._sarvam = None          # lazily-built SarvamAI client (when config.TTS_BACKEND == "sarvam")
        self._speak_started = 0.0
        self._max_speak_s = 30.0     # guard: never report 'speaking' longer than this (stuck-synth safety)

    @property
    def voice_name(self) -> str:
        if config.TTS_BACKEND == "sarvam" and config.SARVAM_API_KEY:
            return f"sarvam:{config.SARVAM_VOICE}"
        if config.TTS_BACKEND == "kokoro":
            return f"kokoro:{config.KOKORO_VOICE}"
        return self._voice.name() if self._voice else "say"

    def speak(self, text: str, wait: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self.stop()
            import time as _t
            self._speak_started = _t.monotonic()
            backend = config.TTS_BACKEND
            if backend == "kokoro":
                spoke = self._speak_kokoro(text)
            elif backend == "sarvam":
                spoke = self._speak_sarvam(text)
            else:
                spoke = False
            if spoke:
                pass                                  # neural backends play via afplay (self._proc); stop/wait/speaking handle it
            elif self._synth is not None:
                u = AVSpeechUtterance.speechUtteranceWithString_(text)
                if self._voice is not None:
                    u.setVoice_(self._voice)
                u.setRate_(config.TTS_RATE)
                u.setPitchMultiplier_(config.TTS_PITCH)
                self._synth.speakUtterance_(u)
            else:
                self._proc = subprocess.Popen(["say", text])
        if wait:
            self.wait()

    def _ensure_kokoro(self):
        if self._kokoro is None:
            from mlx_audio.tts.utils import load_model
            from . import mlx_pool
            self._kokoro = mlx_pool.run(load_model, config.KOKORO_MODEL)
        return self._kokoro

    def _speak_kokoro(self, text: str) -> bool:
        """Generate with Kokoro-82M, play via afplay (reusing the subprocess path). False on any failure/NaN
        so speak() falls back to AVSpeech and the user still hears something."""
        try:
            import numpy as np, tempfile
            import soundfile as sf
            from . import mlx_pool
            m = self._ensure_kokoro()
            chunks = mlx_pool.run(lambda: [np.asarray(r.audio) for r in
                                           m.generate(text=text, voice=config.KOKORO_VOICE, speed=config.KOKORO_SPEED)])
            audio = np.concatenate(chunks) if chunks else None
            if audio is None or not audio.size or bool(np.isnan(audio).any()) or float(np.abs(audio).max()) < 1e-4:
                return False                          # known Kokoro-MLX NaN/silent bug -> AVSpeech fallback
            path = tempfile.mktemp(suffix=".wav")
            sf.write(path, audio.astype("float32"), 24000)
            self._proc = subprocess.Popen(["afplay", path])
            return True
        except Exception:
            return False

    def _ensure_sarvam(self):
        if self._sarvam is None:
            from sarvamai import SarvamAI
            self._sarvam = SarvamAI(api_subscription_key=config.SARVAM_API_KEY,
                                    timeout=config.SARVAM_TIMEOUT)
        return self._sarvam

    def _speak_sarvam(self, text: str) -> bool:
        """Synthesize with Sarvam Bulbul v3 and play via afplay (reusing the subprocess path). Returns False
        on no key / offline / oversized text / any API error so speak() falls back to AVSpeech — a cloud voice
        must never be able to mute the assistant."""
        if not config.SARVAM_API_KEY or len(text) > config.SARVAM_MAX_CHARS:
            return False
        try:
            import tempfile
            from sarvamai.play import save                # decodes the base64 chunks into one valid WAV
            from . import net
            if not net.online("api.sarvam.ai"):
                return False
            audio = self._ensure_sarvam().text_to_speech.convert(
                text=text,
                model="bulbul:v3",
                language_code=config.sarvam_lang_for(text),
                speaker=config.SARVAM_VOICE,
                pace=config.SARVAM_PACE,
                speech_sample_rate=24000,
            )
            path = tempfile.mktemp(suffix=".wav")
            save(audio, path)                             # do NOT just b64-decode+concat: each chunk is a full
            self._proc = subprocess.Popen(["afplay", path])   # WAV, so joining them plays only the first
            return True
        except Exception:
            return False

    def wait(self) -> None:
        if self._proc is not None:                    # Kokoro/say path (afplay/say subprocess)
            self._proc.wait()
            return
        if self._synth is not None:
            import time
            t0 = time.monotonic()
            while not self._synth.isSpeaking() and time.monotonic() - t0 < 1.0:
                time.sleep(0.02)                      # speech starts asynchronously
            while self._synth.isSpeaking():
                time.sleep(0.05)

    def stop(self) -> None:
        if self._synth is not None and self._synth.isSpeaking():
            self._synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None

    @property
    def speaking(self) -> bool:
        import time as _t
        if self._speak_started and _t.monotonic() - self._speak_started > self._max_speak_s:
            return False     # stuck-synth guard: don't let a hung voice mute the mic forever
        av = bool(self._synth.isSpeaking()) if self._synth is not None else False
        proc = self._proc is not None and self._proc.poll() is None
        return av or proc     # AVSpeech OR the afplay/say subprocess (Kokoro path)
