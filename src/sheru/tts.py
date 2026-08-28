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
            if self._synth is not None:
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

    def wait(self) -> None:
        if self._synth is not None:
            import time
            t0 = time.monotonic()
            while not self._synth.isSpeaking() and time.monotonic() - t0 < 1.0:
                time.sleep(0.02)                      # speech starts asynchronously
            while self._synth.isSpeaking():
                time.sleep(0.05)
        elif self._proc is not None:
            self._proc.wait()

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
        if self._synth is not None:
            return bool(self._synth.isSpeaking())
        return self._proc is not None and self._proc.poll() is None
