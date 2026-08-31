"""Apple Voice Processing I/O capture — the front-end Siri/FaceTime use, at the OS level.

`AVAudioEngine`'s input node with `setVoiceProcessingEnabled(True)` runs the system Voice-Processing audio
unit on the mic stream, which gives three things Sheru was faking (badly) in software:

  * AEC (acoustic echo cancellation) — subtracts Sheru's own speaker output from the mic, so its TTS can't
    re-trigger or garble the next capture. Replaces the crude "drop all audio while speaking" echo guard.
  * AGC (automatic gain control) — keeps the level in range without clipping. Retires the mic-volume hacks
    (raising the OS input to 90 % was the self-inflicted clipping → Whisper-gibberish bug).
  * Noise suppression — pulls speech out of fan / room / traffic noise.

This module exposes a small block source (`AvSource`) that delivers float32 **mono 16 kHz** blocks through a
queue, matching the sounddevice callback contract so the existing Silero-VAD loop in audio.py is unchanged.
If the engine can't start (older macOS, no VP unit, permission race) the caller falls back to the raw
sounddevice path — nothing here is load-bearing.
"""
from __future__ import annotations

import logging
import queue
import threading

import numpy as np

from . import config

_log = logging.getLogger("sheru.audio")
_TARGET_SR = config.SAMPLE_RATE  # 16 kHz — what Silero VAD + Whisper expect


def available() -> bool:
    """True if the Voice-Processing capture path can even be attempted (AVFoundation present + enabled)."""
    if not config.VOICE_PROCESSING:
        return False
    try:
        import AVFoundation  # noqa: F401
        return True
    except Exception:
        return False


# --- shared engine ---------------------------------------------------------------------------------------------
# The Voice-Processing audio unit allows only ONE engine on the mic at a time (two conflict — both go silent), so
# the app shares a single persistent AvSource. The always-on wake-word listener reads it when idle; while a
# push-to-talk turn is active it yields (`_ptt` set), so only one consumer drains the single block queue at a time.
_shared: "AvSource | None" = None
_shared_failed = False
_shared_lock = threading.Lock()
_ptt = threading.Event()


def shared() -> "AvSource | None":
    """The one app-wide Voice-Processing source, started on first use. None if VP is off / unavailable / failed
    (caller then falls back to a raw sounddevice stream)."""
    global _shared, _shared_failed
    if not available() or _shared_failed:
        return None
    with _shared_lock:
        if _shared is None:
            try:
                _shared = AvSource().start()
            except Exception as e:
                _shared_failed = True
                _log.warning("Voice-Processing capture unavailable (%s) — using the raw mic instead", e)
                return None
        return _shared


def vp_active() -> bool:
    """True if the shared Voice-Processing engine is the live mic path (so the OS-gain hacks can stand down —
    the VP unit's AGC manages level)."""
    return _shared is not None and not _shared_failed


def set_ptt(active: bool) -> None:
    """Mark a push-to-talk turn active/inactive so the always-on listener yields the shared mic to it."""
    (_ptt.set if active else _ptt.clear)()


def ptt_active() -> bool:
    return _ptt.is_set()


_persistent = False   # True only when the always-on wake-word listener needs the engine kept live between turns


def set_persistent(on: bool) -> None:
    """The always-on listener calls this to keep the shared engine alive across push-to-talk turns. In the default
    push-to-talk-only mode it stays False, so release_shared() actually frees the mic when a conversation ends."""
    global _persistent
    _persistent = on


def release_shared() -> None:
    """Stop the shared Voice-Processing engine and FREE THE MIC (the macOS mic-in-use indicator goes off) when
    nothing needs it — call this when a push-to-talk conversation ends. No-op while the always-on listener holds
    the engine (in that mode the mic is legitimately always live). A later shared() call re-creates it, so the
    mic is live only during an actual conversation, not for the whole app lifetime."""
    global _shared
    if _persistent:
        return
    with _shared_lock:
        s, _shared = _shared, None
    if s is not None:
        s.stop()
        _log.info("mic: released Voice-Processing engine — mic idle")


class AvSource:
    """AVAudioEngine + Voice-Processing capture. `.start()` opens the mic; `.read(timeout)` pops the next
    float32 mono 16 kHz block (raises queue.Empty on timeout); `.stop()` tears it down. Instantiate/​start on
    the thread that will consume — the tap fires on CoreAudio's own real-time thread, independent of any run loop.
    """

    def __init__(self, blocksize: int = 1024, maxsize: int = 400) -> None:
        self._blocksize = blocksize
        self._blocks: queue.Queue[np.ndarray] = queue.Queue(maxsize=maxsize)
        self._eng = None
        self._inp = None
        self._tap = None          # keep a ref so the ObjC block isn't GC'd out from under CoreAudio
        self._sr = _TARGET_SR
        self._rs = None           # stateful resampler when the device isn't already at 16 kHz
        self._logged_drop = False

    def start(self) -> "AvSource":
        import AVFoundation as AV

        eng = AV.AVAudioEngine.alloc().init()
        inp = eng.inputNode()
        ok, err = inp.setVoiceProcessingEnabled_error_(True, None)
        if not ok:
            raise RuntimeError(f"setVoiceProcessingEnabled failed: {err}")
        fmt = inp.outputFormatForBus_(0)
        self._sr = int(fmt.sampleRate())
        if self._sr != _TARGET_SR:
            import soxr
            # STATEFUL streaming resampler — keeps filter state across blocks. (Resampling each block on its own
            # with the one-shot soxr.resample() leaves an edge transient every ~100 ms → garbled STT.)
            self._rs = soxr.ResampleStream(self._sr, _TARGET_SR, 1, dtype="float32", quality="HQ")

        def _tap(buf, when):                       # CoreAudio real-time thread — must never raise
            try:
                n = int(buf.frameLength())
                if n == 0:
                    return
                chans = buf.floatChannelData()     # tuple of per-channel varlists (non-interleaved float32)
                if not chans:
                    return
                a = np.frombuffer(chans[0].as_buffer(n), dtype=np.float32).copy()  # channel 0 only
                if self._rs is not None:
                    a = self._rs.resample_chunk(a)          # stateful 48k→16k; may return a shorter/empty chunk
                    if a is None or a.size == 0:
                        return
                    a = np.ascontiguousarray(a, dtype=np.float32)
                try:
                    self._blocks.put_nowait(a)
                except queue.Full:
                    if not self._logged_drop:
                        self._logged_drop = True
                        _log.warning("AvSource queue full — dropping blocks (consumer too slow?)")
            except Exception as e:                 # a raise here would crash the audio render thread
                _log.debug("AvSource tap error: %s", e)

        inp.installTapOnBus_bufferSize_format_block_(0, self._blocksize, fmt, _tap)
        eng.prepare()
        ok, err = eng.startAndReturnError_(None)
        if not ok:
            try:
                inp.removeTapOnBus_(0)
            except Exception:
                pass
            raise RuntimeError(f"AVAudioEngine start failed: {err}")
        self._eng, self._inp, self._tap = eng, inp, _tap
        _log.info("mic: Voice-Processing I/O (AEC+AGC+NS) @ %d Hz%s", self._sr,
                  "" if self._sr == _TARGET_SR else f" → resampled to {_TARGET_SR}")
        return self

    def read(self, timeout: float) -> np.ndarray:
        """Next block (float32 mono 16 kHz). Raises queue.Empty on timeout."""
        return self._blocks.get(timeout=timeout)

    def drain(self) -> None:
        """Discard any buffered blocks (e.g. to clear the echo of Sheru's just-finished TTS before listening)."""
        try:
            while True:
                self._blocks.get_nowait()
        except queue.Empty:
            pass

    def stop(self) -> None:
        try:
            if self._inp is not None:
                self._inp.removeTapOnBus_(0)
        except Exception:
            pass
        try:
            if self._eng is not None:
                self._eng.stop()
        except Exception:
            pass
        self._eng = self._inp = self._tap = None
