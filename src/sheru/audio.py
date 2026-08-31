"""Always-on microphone pipeline: sounddevice -> Silero VAD (sherpa-onnx) -> speech segments.

Wake-word detection happens *after* transcription (see app.py): every speech segment is transcribed
on-device (~80 ms) and accepted if it starts with the wake word or arrives inside a follow-up window.
This beats a tiny keyword model for an uncommon word like "Sheru" and allows one-shot commands.
"""
from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

import logging

import numpy as np
import sounddevice as sd
import sherpa_onnx

from . import avcapture, config

_log = logging.getLogger("sheru.audio")
BLOCK = 512  # 32 ms @ 16 kHz — Silero's native window
_LOGGED_DEV = "\0"   # last input device we logged (sentinel != any real index/None)


@dataclass
class ListenerConfig:
    vad_threshold: float = 0.2      # lower = more sensitive to quieter speech
    end_silence_s: float = 0.4      # trailing silence that ends a segment
    min_speech_s: float = 0.2
    max_segment_s: float = 12.0
    device: int | str | None = None


def _new_vad(cfg: "ListenerConfig") -> "sherpa_onnx.VoiceActivityDetector":
    vc = sherpa_onnx.VadModelConfig()
    vc.silero_vad.model = str(config.VAD_MODEL)
    vc.silero_vad.threshold = cfg.vad_threshold
    vc.silero_vad.min_silence_duration = cfg.end_silence_s
    vc.silero_vad.min_speech_duration = cfg.min_speech_s
    vc.silero_vad.max_speech_duration = cfg.max_segment_s
    vc.silero_vad.window_size = BLOCK
    vc.sample_rate = config.SAMPLE_RATE
    return sherpa_onnx.VoiceActivityDetector(vc, buffer_size_in_seconds=cfg.max_segment_s + 10)


class _SdSource:
    """Raw sounddevice InputStream as a block source (float32 mono 16 kHz), used when Voice-Processing I/O
    isn't available. Same `.read()/.drain()/.stop()` contract as avcapture.AvSource so the VAD loop is shared."""

    def __init__(self, device, blocksize: int = BLOCK) -> None:
        self._device = device
        self._blocksize = blocksize
        self._blocks: queue.Queue[np.ndarray] = queue.Queue(maxsize=400)
        self._stream = None

    def start(self) -> "_SdSource":
        def _cb(indata, frames, t, status):
            try:
                self._blocks.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass
        self._stream = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
                                      blocksize=self._blocksize, device=self._device, callback=_cb)
        self._stream.start()
        return self

    def read(self, timeout: float) -> np.ndarray:
        return self._blocks.get(timeout=timeout)

    def drain(self) -> None:
        try:
            while True:
                self._blocks.get_nowait()
        except queue.Empty:
            pass

    def stop(self) -> None:
        try:
            self._stream.stop(); self._stream.close()
        except Exception:
            pass


class Listener:
    def __init__(self, cfg: ListenerConfig | None = None, is_busy: Callable[[], bool] | None = None) -> None:
        self.cfg = cfg or ListenerConfig()
        self.is_busy = is_busy or (lambda: False)   # True while Sheru itself is talking -> drop audio (echo)
        self.muted = threading.Event()
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._stop = threading.Event()
        self.vad = _new_vad(self.cfg)
        self._src = None
        self._shared = False
        self.speech_active = False
        self._nblk = 0

    def start(self) -> "Listener":
        # Prefer the one shared Voice-Processing engine (AEC/AGC/NS); fall back to a raw sounddevice stream.
        self._src = avcapture.shared()
        self._shared = self._src is not None
        if not self._shared:
            self._src = _SdSource(self.cfg.device).start()
        threading.Thread(target=self._loop, name="sheru-listener", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if not self._shared and self._src is not None:   # own sd stream — close it. The shared VP engine is
            self._src.stop()                             # app-wide and must outlive this listener.

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self._shared and avcapture.ptt_active():   # a push-to-talk turn owns the shared mic — yield to it
                time.sleep(0.05)
                continue
            try:
                block = self._src.read(0.2)
            except queue.Empty:
                continue
            if self.muted.is_set() or self.is_busy():      # muted, or Sheru is speaking -> discard (AEC also cancels echo)
                continue
            self.vad.accept_waveform(block)
            active = self.vad.is_speech_detected()
            if active != self.speech_active:
                self.speech_active = active
                _log.info("VAD %s", "speech-start" if active else "speech-end")
            self._nblk += 1
            if self._nblk % 120 == 0:      # ~every 3.8s: prove audio is flowing
                _log.info("audio alive: rms=%.4f speech=%s", float(np.sqrt((block**2).mean())), active)
            while not self.vad.empty():
                seg = self.vad.front
                self.vad.pop()
                audio = np.asarray(seg.samples, dtype=np.float32)
                _log.info("segment %.1fs rms=%.4f", audio.size / config.SAMPLE_RATE, float(np.sqrt((audio**2).mean())))
                if audio.size >= config.SAMPLE_RATE * self.cfg.min_speech_s:
                    self._q.put(audio)

    def segments(self):
        """Yield finished speech segments (float32 @ 16 kHz)."""
        while not self._stop.is_set():
            try:
                yield self._q.get(timeout=0.5)
            except queue.Empty:
                continue


LEVEL = {"v": 0.0}      # live mic amplitude (0..1, smoothed) during capture_once — drives the listening orb


def list_input_devices() -> list[tuple[int, str]]:
    """(index, name) for every input-capable audio device — for the menu-bar mic picker."""
    out = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                out.append((i, d["name"]))
    except Exception:
        pass
    return out


def _builtin_index(devs):
    for i, name in devs:
        if any(k in name.lower() for k in ("macbook", "built-in", "built in", "internal")):
            return i
    return None


def preferred_device():
    """Which input device to open. Yash's rule: ALWAYS use the MacBook's built-in mic when it exists — it isolates
    the voice far better than his headset, which picks up room noise (garbling STT). The built-in wins over any
    saved choice; an explicit override is only honoured when NO built-in mic is present. Falls back to the system
    default (None) on a machine with no built-in mic and no valid saved choice."""
    devs = list_input_devices()
    builtin = _builtin_index(devs)
    if builtin is not None:
        return builtin
    pref = config.MIC_DEVICE                                   # no built-in mic here -> honour a saved choice
    if pref not in (None, ""):
        try:
            return int(pref)
        except (ValueError, TypeError):
            for i, name in devs:
                if str(pref).lower() in name.lower():
                    return i
    return None


def capture_once(max_wait: float = 8.0, cfg: "ListenerConfig | None" = None) -> "np.ndarray | None":
    """Open the mic, return the FIRST complete speech segment (float32 @16k) or None on timeout, then release
    the mic. Push-to-talk: while this runs the always-on listener yields the shared Voice-Processing engine.
    Prefers Apple Voice-Processing I/O (AEC/AGC/NS); falls back to a raw sounddevice stream."""
    import queue as _q
    import time as _t
    cfg = cfg or ListenerConfig()
    vad = _new_vad(cfg)

    # `gain` boosts ONLY the VAD's detection copy, never the STT audio. Voice-Processing I/O already levels the
    # signal (AGC), so it needs no boost; the raw sounddevice path does, for quiet speech.
    src = avcapture.shared()
    shared = src is not None
    default_gain = 1.0 if shared else 4.0
    gain = float(os.environ["SHERU_MIC_GAIN"]) if "SHERU_MIC_GAIN" in os.environ else default_gain
    if shared:
        avcapture.set_ptt(True)          # the always-on listener yields the shared mic to this turn
        src.drain()                      # clear any backlog (incl. the tail of Sheru's just-finished TTS)
    else:
        dev = cfg.device if cfg.device is not None else preferred_device()   # honour the chosen mic (else built-in)
        global _LOGGED_DEV
        if dev != _LOGGED_DEV:                                               # log the mic once (and on any change)
            try:
                _LOGGED_DEV = dev
                _log.info("mic: raw capture on device %s (%s)", dev,
                          sd.query_devices(dev)["name"] if dev is not None else "system default")
            except Exception:
                pass
        src = _SdSource(dev).start()

    t0 = _t.monotonic(); seg = None
    raw: list = []          # keep the clean, un-gained audio for the STT
    speech_seen = False
    try:
        while _t.monotonic() - t0 < max_wait:
            try:
                block = src.read(0.2)
            except _q.Empty:
                continue
            raw.append(block)
            LEVEL["v"] = 0.55 * LEVEL["v"] + 0.45 * min(1.0, float(np.sqrt((block ** 2).mean())) * 12.0)  # for the orb
            vad.accept_waveform(np.clip(block * gain, -1.0, 1.0).astype(np.float32))  # gained -> VAD only
            if vad.is_speech_detected():
                speech_seen = True
            if not vad.empty():
                s = vad.front
                start, n = int(s.start), len(s.samples)
                allraw = np.concatenate(raw)
                seg = allraw[start:start + n] if 0 <= start < allraw.size else np.asarray(s.samples, dtype=np.float32)
                vad.pop()
                break
        if seg is None:                       # timed out — salvage
            try:
                vad.flush()
            except Exception:
                pass
            if not vad.empty():
                s = vad.front
                start, n = int(s.start), len(s.samples)
                allraw = np.concatenate(raw) if raw else np.zeros(0, np.float32)
                seg = allraw[start:start + n] if 0 <= start < allraw.size else np.asarray(s.samples, dtype=np.float32)
            elif speech_seen and raw:         # heard speech but no clean segment -> use the whole take
                seg = np.concatenate(raw)
    finally:
        LEVEL["v"] = 0.0
        if shared:
            avcapture.set_ptt(False)     # hand the shared mic back to the always-on listener; leave it running
        else:
            src.stop()
    # Energy floor: if the VAD tripped on room hiss / a transient, the "segment" is essentially silence. Whisper
    # hallucinates canned phrases on near-silence ('Thank you.', 'I'm sorry.') that a text-only confidence gate
    # can't always catch, so don't even transcribe it — treat it as no speech. Real speech clears this easily
    # (Voice-Processing AGC levels it well above the floor).
    if seg is not None and seg.size:
        pk = float(np.abs(seg).max()); rms = float(np.sqrt((seg ** 2).mean()))
        if pk < 0.02 and rms < 0.006:
            _log.info("mic: segment below speech floor (peak=%.4f rms=%.5f) — treating as silence", pk, rms)
            return None
    return seg
