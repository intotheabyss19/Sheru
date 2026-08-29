"""Siri-style listening orb — approach A (Core Animation) + E (audio-reactive).

A small, borderless, always-on-top orb that pulses gently at rest and swells with your VOICE (live mic RMS).
GPU-composited via CALayer/CAGradientLayer (60fps, ~zero CPU). This is a STANDALONE, previewable component so
the look can be judged before it's wired into activation:

    uv run python -m sheru.orb        # shows the orb for ~20s, reacting to your mic; click it to print a hit

Interaction the app will use once approved: tap mic -> orb appears (listening); click orb -> chat panel opens;
listening ends -> orb fades. (Metal fluid-blob = approach B, particle swirl = D — scaffolded for overnight.)
"""
from __future__ import annotations

import math
import threading
import time

import objc
from AppKit import (
    NSApp, NSApplication, NSBackingStoreBuffered, NSColor, NSFloatingWindowLevel, NSPanel, NSView,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorStationary,
)
from Foundation import NSMakeRect, NSObject, NSPoint
from PyObjCTools import AppHelper
from Quartz import CAGradientLayer, CABasicAnimation, CATransaction, CATransform3DMakeScale

ORB = 180                    # window + orb diameter (px)
_amp = {"v": 0.0}            # shared live mic amplitude 0..1 (smoothed), written by the sampler thread


class _OrbView(NSView):
    def initWithFrame_click_(self, frame, on_click):
        self = objc.super(_OrbView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = on_click
        self.setWantsLayer_(True)
        r = ORB * 0.34
        cx, cy = ORB / 2, ORB / 2
        # the glowing orb: a radial gradient disc with a soft outer glow
        orb = CAGradientLayer.layer()
        orb.setType_("radial")                                # kCAGradientLayerRadial
        orb.setColors_([
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.55, 0.80, 1.0, 1.0).CGColor(),   # bright core
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.40, 0.45, 0.98, 1.0).CGColor(),
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.65, 0.35, 0.95, 0.0).CGColor(),   # fades out at the rim
        ])
        orb.setLocations_([0.0, 0.55, 1.0])
        orb.setStartPoint_(NSPoint(0.5, 0.5))
        orb.setEndPoint_(NSPoint(1.0, 1.0))
        orb.setFrame_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))
        orb.setCornerRadius_(r)
        orb.setShadowColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(0.5, 0.6, 1.0, 1.0).CGColor())
        orb.setShadowRadius_(24.0)
        orb.setShadowOpacity_(0.9)
        orb.setShadowOffset_((0, 0))
        self.layer().addSublayer_(orb)
        self._orb = orb
        self._r = r
        # gentle idle breathing so it's alive even in silence (amplitude adds on top)
        pulse = CABasicAnimation.animationWithKeyPath_("transform.scale")
        pulse.setFromValue_(0.92)
        pulse.setToValue_(1.04)
        pulse.setDuration_(1.6)
        pulse.setAutoreverses_(True)
        pulse.setRepeatCount_(1e9)
        orb.addAnimation_forKey_(pulse, "breathe")
        return self

    @objc.python_method
    def apply_level(self, v):
        # scale the orb by live amplitude, on top of the idle breathe; no implicit animation (smooth per-frame)
        s = 1.0 + 0.6 * max(0.0, min(1.0, v))
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self._orb.setTransform_(_scale(s))
        CATransaction.commit()

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()


def _scale(s):
    return CATransform3DMakeScale(s, s, 1.0)


class ListeningOrb(NSObject):
    """show()/hide() a click-through-to-chat listening orb; call set_level(0..1) each audio frame for reactivity."""

    def initWithOnClick_(self, on_click):
        self = objc.super(ListeningOrb, self).init()
        if self is None:
            return None
        self._on_click = on_click
        self._panel = None
        self._timer = None
        return self

    @objc.python_method
    def _build(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        p = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, ORB, ORB), style, NSBackingStoreBuffered, False)
        p.setLevel_(NSFloatingWindowLevel)
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setIgnoresMouseEvents_(False)
        view = _OrbView.alloc().initWithFrame_click_(NSMakeRect(0, 0, ORB, ORB), self._on_click)
        p.setContentView_(view)
        self._view = view
        # bottom-centre of the main screen, a little up from the dock
        from AppKit import NSScreen
        f = NSScreen.mainScreen().frame()
        p.setFrameOrigin_((f.size.width / 2 - ORB / 2, 120))
        self._panel = p

    @objc.python_method
    def show(self):
        def do():
            if self._panel is None:
                self._build()
            self._panel.orderFrontRegardless()
        AppHelper.callAfter(do)

    @objc.python_method
    def hide(self):
        def do():
            if self._panel is not None:
                self._panel.orderOut_(None)
        AppHelper.callAfter(do)

    @objc.python_method
    def set_level(self, v):
        def do():
            if getattr(self, "_view", None) is not None:
                self._view.apply_level(v)
        AppHelper.callAfter(do)


# ---- standalone preview: shows the orb reacting to your mic for ~20s ------------------------------------------
def _mic_sampler():
    """Fill _amp['v'] with a smoothed live mic level (0..1) so the preview is audio-reactive."""
    try:
        import numpy as np
        import sounddevice as sd
        from . import config
        from .audio import preferred_device
        sm = 0.0

        def cb(indata, frames, t, status):
            nonlocal sm
            rms = float(np.sqrt((indata[:, 0] ** 2).mean()))
            level = min(1.0, rms * 12.0)                 # scale quiet speech up into a visible range
            sm = 0.6 * sm + 0.4 * level                  # smoothing
            _amp["v"] = sm

        with sd.InputStream(samplerate=config.SAMPLE_RATE, channels=1, dtype="float32",
                            blocksize=512, device=preferred_device(), callback=cb):
            time.sleep(20)
    except Exception as e:
        print("mic sampler off:", e)


def main():
    app = NSApplication.sharedApplication()
    orb = ListeningOrb.alloc().initWithOnClick_(lambda: print("orb clicked -> (would open chat)"))
    orb.show()
    threading.Thread(target=_mic_sampler, daemon=True).start()

    from Foundation import NSTimer
    t0 = time.monotonic()

    class _T(NSObject):
        def tick_(self, _):
            orb.set_level(_amp["v"])
            if time.monotonic() - t0 > 22:        # end the preview after ~22s
                orb.hide()
                AppHelper.stopEventLoop()
    t = _T.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1 / 30.0, t, "tick:", None, True)
    print("orb preview: speak into the mic — it should swell with your voice. ~22s. Click it to test the tap.")
    AppHelper.runConsoleEventLoop()


if __name__ == "__main__":
    main()
