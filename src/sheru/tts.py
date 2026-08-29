"""Speech output. AVSpeechSynthesizer via pyobjc (<100 ms to first audio); `say` as fallback."""
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
        self._speak_started = 0.0
        self._max_speak_s = 30.0     # guard: never report 'speaking' longer than this (stuck-synth safety)

    @property
    def voice_name(self) -> str:
        return self._voice.name() if self._voice else "say"

    def speak(self, text: str, wait: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self.stop()
            import time as _t
            self._speak_started = _t.monotonic()
            spoke = self._speak_kokoro(text) if config.TTS_BACKEND == "kokoro" else False
            if spoke:
                pass                                  # Kokoro plays via afplay (self._proc); stop/wait/speaking handle it
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
