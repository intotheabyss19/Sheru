"""Tests for the Voice-Processing I/O capture path (AEC/AGC/NS via AVAudioEngine) and the shared-engine
coordination that lets the always-on listener and push-to-talk share ONE mic (two VP engines conflict).

The real-mic checks are best-effort: they start the system Voice-Processing engine and confirm blocks flow.
On a machine with no mic / no VP unit they degrade to a skip, never a failure.

Run: uv run python tests/test_audio_voiceproc.py
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
from sheru import avcapture, audio, stt

fails: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"  {'✓' if ok else '✗'} {name}")
    if not ok:
        fails.append(name)


# ── STT silence/noise hallucination gate (pure, no hardware) ─────────────────────────────────────────
def _seg(comp=1.5, lp=-0.3, nsp=0.1):
    return {"segments": [{"compression_ratio": comp, "avg_logprob": lp, "no_speech_prob": nsp, "text": "x"}]}

check("repetitive hallucination (high compression_ratio) is dropped",
      stt._hallucinated(_seg(comp=13.2)))            # the real 'I'm sorry. I'm sorry. …' signature
check("both-signals-bad noise is dropped", stt._hallucinated(_seg(lp=-1.5, nsp=0.9)))
check("low logprob ALONE is KEPT (real but imperfect speech)", not stt._hallucinated(_seg(lp=-1.5, nsp=0.1)))
check("high no-speech ALONE is KEPT (falsely-confident model)", not stt._hallucinated(_seg(nsp=0.95, lp=-0.3)))
check("normal speech stats are KEPT", not stt._hallucinated(_seg(comp=1.8, lp=-0.3, nsp=0.1)))
check("a confident short command is KEPT", not stt._hallucinated(_seg(comp=0.9, lp=-0.2, nsp=0.0)))
check("empty result (no segments) is not flagged", not stt._hallucinated({"segments": []}))


# ── module contract (no hardware) ───────────────────────────────────────────────────────────────────
check("available() is a bool", isinstance(avcapture.available(), bool))
check("ptt flag round-trips", (avcapture.set_ptt(True) or avcapture.ptt_active()) and
      (avcapture.set_ptt(False) or not avcapture.ptt_active()))
check("AvSource has the read/drain/stop source contract",
      all(callable(getattr(avcapture.AvSource, m, None)) for m in ("start", "read", "drain", "stop")))
check("_SdSource fallback has the same source contract",
      all(callable(getattr(audio._SdSource, m, None)) for m in ("start", "read", "drain", "stop")))
check("_new_vad builds a detector from a ListenerConfig",
      audio._new_vad(audio.ListenerConfig()) is not None)

# ── real Voice-Processing engine (best-effort) ──────────────────────────────────────────────────────
if avcapture.available():
    src = avcapture.shared()
    check("shared() starts the Voice-Processing engine", src is not None)
    if src is not None:
        check("vp_active() true once the shared engine is up", avcapture.vp_active())
        got, t0 = 0, time.monotonic()
        while time.monotonic() - t0 < 1.5:            # blocks flow without an NSRunLoop spin (as inside Sheru's threads)
            try:
                b = src.read(0.2)
                got += 1
                if got == 1:
                    check("block is float32 mono 16 kHz", b.dtype == np.float32 and b.ndim == 1)
            except Exception:
                pass
        check("Voice-Processing engine delivers audio blocks", got > 0)

        # shared coordination: while a PTT turn is active the listener must yield (no second engine)
        lis = audio.Listener(audio.ListenerConfig()).start()
        check("listener attaches to the shared engine (not its own stream)", lis._shared)
        avcapture.set_ptt(True)
        check("ptt flag steers coordination", avcapture.ptt_active())
        avcapture.set_ptt(False)
        lis.stop()                                    # listener.stop() releases the shared engine (frees the mic)

        # release_shared() frees the mic when idle (PTT-only mode) so the indicator isn't always-on
        src2 = avcapture.shared()
        check("shared() re-creates the engine after a release", src2 is not None)
        avcapture.release_shared()
        check("release_shared() frees the mic (engine cleared) when not persistent", not avcapture.vp_active())
        # a persistent holder (the always-on listener) must keep the mic live across turns
        avcapture.shared(); avcapture.set_persistent(True)
        avcapture.release_shared()
        check("release_shared() is a NO-OP while a persistent holder needs the mic", avcapture.vp_active())
        avcapture.set_persistent(False); avcapture.release_shared()
else:
    print("  – Voice-Processing unavailable here; skipped the real-mic checks (raw sounddevice fallback active)")

print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
