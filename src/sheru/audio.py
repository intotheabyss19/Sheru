"""Always-on microphone pipeline: sounddevice -> Silero VAD (sherpa-onnx) -> speech segments.

Wake-word detection happens *after* transcription (see app.py): every speech segment is transcribed
on-device (~80 ms) and accepted if it starts with the wake word or arrives inside a follow-up window.
This beats a tiny keyword model for an uncommon word like "Sheru" and allows one-shot commands.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

import logging

import numpy as np
import sounddevice as sd
import sherpa_onnx

from . import config

_log = logging.getLogger("sheru.audio")
BLOCK = 512  # 32 ms @ 16 kHz — Silero's native window


@dataclass
class ListenerConfig:
    vad_threshold: float = 0.2      # lower = more sensitive to quieter speech
    end_silence_s: float = 0.4      # trailing silence that ends a segment
    min_speech_s: float = 0.2
    max_segment_s: float = 12.0
    device: int | str | None = None


class Listener:
    def __init__(self, cfg: ListenerConfig | None = None, is_busy: Callable[[], bool] | None = None) -> None:
        self.cfg = cfg or ListenerConfig()
        self.is_busy = is_busy or (lambda: False)   # True while Sheru itself is talking -> drop audio (echo)
        self.muted = threading.Event()
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._blocks: queue.Queue[np.ndarray] = queue.Queue(maxsize=400)
        self._stop = threading.Event()
        self.vad = self._make_vad()
        self.speech_active = False
        self._nblk = 0

    def _make_vad(self) -> sherpa_onnx.VoiceActivityDetector:
        vc = sherpa_onnx.VadModelConfig()
        vc.silero_vad.model = str(config.VAD_MODEL)
        vc.silero_vad.threshold = self.cfg.vad_threshold
        vc.silero_vad.min_silence_duration = self.cfg.end_silence_s
        vc.silero_vad.min_speech_duration = self.cfg.min_speech_s
        vc.silero_vad.max_speech_duration = self.cfg.max_segment_s
        vc.silero_vad.window_size = BLOCK
        vc.sample_rate = config.SAMPLE_RATE
        return sherpa_onnx.VoiceActivityDetector(vc, buffer_size_in_seconds=self.cfg.max_segment_s + 10)

    def _callback(self, indata, frames, t, status):  # sounddevice thread
        if self.muted.is_set() or self.is_busy():
            return
        try:
            self._blocks.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass

    def start(self) -> "Listener":
        self._stream = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
                                      blocksize=BLOCK, device=self.cfg.device, callback=self._callback)
        self._stream.start()
        threading.Thread(target=self._loop, name="sheru-listener", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._stream.stop(); self._stream.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                block = self._blocks.get(timeout=0.2)
            except queue.Empty:
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


def preferred_device():
    """Which input device to open: the user's saved choice (config.MIC_DEVICE = index or name substring), else
    the built-in MacBook mic (best voice isolation / noise rejection), else the system default (None)."""
    pref = config.MIC_DEVICE
    devs = list_input_devices()
    if pref not in (None, ""):
        try:
            return int(pref)                                   # an explicit device index
        except (ValueError, TypeError):
            for i, name in devs:
                if str(pref).lower() in name.lower():
                    return i
    for i, name in devs:                                       # auto: prefer the built-in mic
        if any(k in name.lower() for k in ("macbook", "built-in", "built in", "internal")):
            return i
    return None


def capture_once(max_wait: float = 8.0, cfg: "ListenerConfig | None" = None) -> "np.ndarray | None":
    """Open the mic, return the FIRST complete speech segment (float32 @16k) or None on timeout, then close
    the mic. Push-to-talk: the mic (and its indicator) is live only for this call."""
    import queue as _q
    import time as _t
    cfg = cfg or ListenerConfig()
    vc = sherpa_onnx.VadModelConfig()
    vc.silero_vad.model = str(config.VAD_MODEL)
    vc.silero_vad.threshold = cfg.vad_threshold
    vc.silero_vad.min_silence_duration = cfg.end_silence_s
    vc.silero_vad.min_speech_duration = cfg.min_speech_s
    vc.silero_vad.max_speech_duration = cfg.max_segment_s
    vc.silero_vad.window_size = BLOCK
    vc.sample_rate = config.SAMPLE_RATE
    vad = sherpa_onnx.VoiceActivityDetector(vc, buffer_size_in_seconds=cfg.max_segment_s + 10)
    blocks: "_q.Queue" = _q.Queue(maxsize=400)

    def _cb(indata, frames, t, status):
        try:
            blocks.put_nowait(indata[:, 0].copy())
        except _q.Full:
            pass

    import os
    gain = float(os.environ.get("SHERU_MIC_GAIN", "4.0"))   # boosts ONLY the VAD's copy, not the STT audio
    dev = cfg.device if cfg.device is not None else preferred_device()   # honour the chosen mic (was ignored -> built-in)
    stream = sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=BLOCK, device=dev, callback=_cb)
    stream.start()
    t0 = _t.monotonic(); seg = None
    raw: list = []          # keep the clean, un-gained audio for the STT
    speech_seen = False
    try:
        while _t.monotonic() - t0 < max_wait:
            try:
                block = blocks.get(timeout=0.2)
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
        stream.stop(); stream.close()
    return seg
