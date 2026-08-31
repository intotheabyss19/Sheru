"""Speech output. AVSpeechSynthesizer via pyobjc (<100 ms to first audio); `say` as fallback.

Optional neural backends (config.TTS_BACKEND): "kokoro" (local, English) and "sarvam" (cloud Bulbul v3,
real Hindi + 10 other Indian languages). Both degrade to AVSpeech on any failure."""
from __future__ import annotations

import queue
import re
import subprocess
import threading

from . import config

_URL = re.compile(r"https?://\S+|www\.\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001FA00-\U0001FAFF←-⇿⬀-⯿✀-➿]")


def _patch_phonemizer_language_switch() -> None:
    """Kokoro's English espeak fallback keeps language-switch flags for OOV words (names like 'Satya'), and
    Kokoro then VOCALIZES those (hi)/(fr) markers as alien gibberish. misaki's EspeakG2P uses 'remove-flags'
    but its EspeakFallback doesn't — so force every espeak backend to 'remove-flags'. Idempotent; run before
    Kokoro loads (an already-built backend keeps its old policy)."""
    try:
        from phonemizer.backend import EspeakBackend
        if getattr(EspeakBackend, "_sheru_no_lang_switch", False):
            return
        _orig = EspeakBackend.__init__

        def _init(self, *a, **k):
            k.setdefault("language_switch", "remove-flags")
            return _orig(self, *a, **k)

        EspeakBackend.__init__ = _init
        EspeakBackend._sheru_no_lang_switch = True
    except Exception:
        pass


def _romanize(text: str) -> str:
    """Devanagari -> Roman/Hinglish so the English voice speaks 'gaana bajaa raha hoon', not gibberish/'Russian'.
    English text passes through untouched. Best-effort: keeps things intelligible, not academically perfect."""
    if not any("ऀ" <= c <= "ॿ" for c in text):
        return text
    try:
        import unicodedata
        from indic_transliteration.sanscript import transliterate, DEVANAGARI, IAST
        out = transliterate(text, DEVANAGARI, IAST)
        out = "".join(c for c in unicodedata.normalize("NFKD", out) if not unicodedata.combining(c))
        out = out.replace("~", "")                          # chandrabindu artifact
        out = re.sub(r"[^\x00-\x7f]", "", out)              # drop any leftover non-ASCII
        return re.sub(r"\s+", " ", out).strip()
    except Exception:
        return text                                         # never let transliteration failure mute Sheru


def _for_speech(text: str) -> str:
    """Romanize Devanagari (so it's pronounceable), then strip markdown/code/URLs/emoji so nothing reads as
    'asterisk asterisk' — Claude & search replies are markdown."""
    text = _romanize(text)
    t = re.sub(r"```.*?```", " ", text, flags=re.S)        # fenced code blocks
    t = t.replace("`", "")                                 # inline code backticks
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)       # [text](url) / image -> text
    t = _URL.sub("a link", t)                              # bare URLs
    t = re.sub(r"\*+([^*]+)\*+", r"\1", t)                 # *italic* / **bold** -> inner text
    t = t.replace("*", "")                                 # stray asterisks / bullets
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)            # leading markdown headings (keep inline C#, #1)
    t = re.sub(r"(?m)^\s*[-•>]\s+", "", t)                 # bullet / blockquote markers
    t = re.sub(r"(?m)^\s*\d+\.\s+", "", t)                 # numbered-list markers
    t = t.replace("|", " ")                                # table pipes
    t = _EMOJI.sub("", t)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{2,}", ". ", t).strip()
    return t

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
        self._max_speak_s = 30.0     # guard: never report 'speaking' longer than this PER utterance (stuck-synth)
        self._q: queue.Queue = queue.Queue()   # sentences to speak IN ORDER — a streamed reply no longer cuts itself off
        self._worker: threading.Thread | None = None
        self._current: str | None = None       # utterance being spoken right now (None between/idle)

    @property
    def voice_name(self) -> str:
        if config.TTS_BACKEND == "sarvam" and config.SARVAM_API_KEY:
            return f"sarvam:{config.SARVAM_VOICE}"
        if config.TTS_BACKEND == "kokoro":
            return f"kokoro:{config.KOKORO_VOICE}"
        return self._voice.name() if self._voice else "say"

    def speak(self, text: str, wait: bool = False) -> None:
        """Enqueue text to be spoken. A streamed reply arrives as many speak() calls; queuing plays them in
        order instead of each one interrupting the last (which left only the final fragment audible)."""
        text = _for_speech(text)
        if not text:
            return
        self._ensure_worker()
        self._q.put(text)
        if wait:
            self.wait()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="sheru-speaker", daemon=True)
                self._worker.start()

    def _run(self) -> None:
        import time as _t
        while True:
            try:
                text = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            self._current = text
            self._speak_started = _t.monotonic()
            try:
                self._play_one(text)          # synthesize + play + BLOCK until this utterance finishes
            except Exception:
                pass
            self._current = None

    def _play_one(self, text: str) -> None:
        backend = config.TTS_BACKEND
        with self._lock:
            spoke = (self._speak_kokoro(text) if backend == "kokoro" else
                     self._speak_sarvam(text) if backend == "sarvam" else False)
            if not spoke:                             # neural failed/off -> AVSpeech, else `say`
                if self._synth is not None:
                    u = AVSpeechUtterance.speechUtteranceWithString_(text)
                    if self._voice is not None:
                        u.setVoice_(self._voice)
                    u.setRate_(config.TTS_RATE)
                    u.setPitchMultiplier_(config.TTS_PITCH)
                    self._synth.speakUtterance_(u)
                else:
                    self._proc = subprocess.Popen(["say", text])
        self._wait_current()                         # don't start the next sentence until this one is done

    def _wait_current(self) -> None:
        import time as _t
        p = self._proc
        if p is not None:                            # afplay/say subprocess (Kokoro/Sarvam/say)
            try:
                p.wait()
            except Exception:
                pass
            return
        if self._synth is not None:                  # AVSpeech
            t0 = _t.monotonic()
            while not self._synth.isSpeaking() and _t.monotonic() - t0 < 1.0:
                _t.sleep(0.02)
            while self._synth.isSpeaking():
                _t.sleep(0.05)

    def _ensure_kokoro(self):
        if self._kokoro is None:
            _patch_phonemizer_language_switch()      # MUST run before Kokoro's g2p backend is built
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
            rms = float(np.sqrt((audio ** 2).mean()))  # Kokoro renders ~-27 dBFS (far too quiet). LOUDNESS-normalize
            if rms > 1e-4:                              # to a target RMS (peak-norm alone only reached ~-20 dBFS —
                audio = np.clip(audio * (config.TTS_GAIN / rms), -1.0, 1.0).astype("float32")  # still quiet); clip the rare peak.
            path = tempfile.mktemp(suffix=".wav")
            sf.write(path, audio, 24000)
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
        """Block until the whole queue has been spoken (all streamed sentences), not just the current one."""
        import time as _t
        while (not self._q.empty()) or self._current is not None or self._proc_alive() or self._synth_speaking():
            _t.sleep(0.05)

    def stop(self) -> None:
        """Interrupt: drop every queued sentence and kill whatever is playing now."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        with self._lock:
            if self._synth is not None and self._synth.isSpeaking():
                self._synth.stopSpeakingAtBoundary_(AVSpeechBoundaryImmediate)
            if self._proc is not None and self._proc.poll() is None:
                self._proc.terminate()
            self._proc = None
        self._current = None

    def _proc_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _synth_speaking(self) -> bool:
        return bool(self._synth.isSpeaking()) if self._synth is not None else False

    @property
    def speaking(self) -> bool:
        import time as _t
        # stuck-synth guard applies PER utterance and only when nothing is queued behind it — a long multi-
        # sentence answer keeps 'speaking' True the whole time (each sentence resets _speak_started).
        if (self._speak_started and _t.monotonic() - self._speak_started > self._max_speak_s
                and self._q.empty() and self._current is None):
            return False
        return (not self._q.empty()) or self._current is not None or self._proc_alive() or self._synth_speaking()
