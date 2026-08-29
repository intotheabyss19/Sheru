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
import sys
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
from Quartz import CALayer, CAGradientLayer, CAEmitterLayer, CAEmitterCell, CATransaction, CATransform3DMakeScale

WIN, ORB = 140, 50           # WIN = transparent window sized to sit flush in the corner (room for the glow +
#                              swell, no clipping, no menu-bar overlap); ORB = the orb disc diameter
_amp = {"v": 0.0}            # shared live mic amplitude 0..1 (smoothed), written by the sampler thread


class _OrbView(NSView):
    def initWithFrame_click_(self, frame, on_click):
        self = objc.super(_OrbView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = on_click
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(False)                 # never clip the glow to the view rect
        r = ORB / 2
        cx, cy = WIN / 2, WIN / 2                             # centre the orb in the roomy window
        # the glowing orb: a radial gradient disc with a soft outer glow
        orb = CAGradientLayer.layer()
        orb.setType_("radial")                                # kCAGradientLayerRadial
        orb.setColors_([
            NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 0.88, 0.46, 1.0).CGColor(),    # bright sun core
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.96, 0.56, 0.13, 1.0).CGColor(),   # lion dark yellow-orange
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.86, 0.33, 0.03, 0.0).CGColor(),   # deep orange, fades at rim
        ])
        orb.setLocations_([0.0, 0.55, 1.0])
        orb.setStartPoint_(NSPoint(0.5, 0.5))
        orb.setEndPoint_(NSPoint(1.0, 1.0))
        orb.setFrame_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))
        orb.setCornerRadius_(r)
        orb.setShadowColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 0.62, 0.16, 1.0).CGColor())  # sun glow
        orb.setShadowRadius_(r * 0.55)                        # radiant glow, scales with the orb
        orb.setShadowOpacity_(0.95)
        orb.setShadowOffset_((0, 0))
        self.layer().addSublayer_(orb)
        self._orb = orb
        self._r = r
        return self

    @objc.python_method
    def apply_level(self, v):
        # single source of scale (no CA-animation override, which was hiding the voice): a gentle idle breathe
        # PLUS live amplitude, recomputed every frame so it actually reacts to your voice.
        idle = 0.05 * (0.5 + 0.5 * math.sin(time.monotonic() * 3.0))
        s = 1.0 + idle + 0.55 * max(0.0, min(1.0, v))         # swell kept within the flush corner window
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
        self._view_cls = _OrbView          # swap to _ParticleView for the particle style
        return self

    @objc.python_method
    def _build(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        p = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIN, WIN), style, NSBackingStoreBuffered, False)
        p.setLevel_(NSFloatingWindowLevel)
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(False)
        p.setIgnoresMouseEvents_(False)
        view = self._view_cls.alloc().initWithFrame_click_(NSMakeRect(0, 0, WIN, WIN), self._on_click)
        p.setContentView_(view)
        self._view = view
        # place the ORB (centred in the roomy window) near the top-right corner, under the menu bar; the extra
        # window padding around it stays transparent so the glow/swell never hits a visible edge
        from AppKit import NSScreen
        vf = NSScreen.mainScreen().visibleFrame()
        # window FLUSH in the top-right of the visible area (top under the menu bar, right at the edge). The orb
        # is centred, so its padding is EQUAL on top and right, and the window never overlaps the menu bar — so
        # macOS can't shove it down (which was inflating the top gap vs the right).
        p.setFrameOrigin_((vf.origin.x + vf.size.width - WIN,
                           vf.origin.y + vf.size.height - WIN))
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


# ---- approach D: audio-reactive particle swirl (CAEmitterLayer) ----------------------------------------------
def _dot_image(d: int = 48):
    """A soft warm radial dot (CGImage) used as the particle sprite."""
    from Quartz import (
        CGColorSpaceCreateDeviceRGB, CGBitmapContextCreate, CGGradientCreateWithColorComponents,
        CGContextDrawRadialGradient, CGBitmapContextCreateImage,
        kCGImageAlphaPremultipliedLast, kCGGradientDrawsAfterEndLocation,
    )
    cs = CGColorSpaceCreateDeviceRGB()
    ctx = CGBitmapContextCreate(None, d, d, 8, d * 4, cs, kCGImageAlphaPremultipliedLast)
    grad = CGGradientCreateWithColorComponents(
        cs, [1.0, 0.93, 0.70, 1.0,  1.0, 0.55, 0.12, 0.0], [0.0, 1.0], 2)   # warm core -> transparent
    c = d / 2.0
    CGContextDrawRadialGradient(ctx, grad, (c, c), 0.0, (c, c), c, kCGGradientDrawsAfterEndLocation)
    return CGBitmapContextCreateImage(ctx)


class _ParticleView(NSView):
    def initWithFrame_click_(self, frame, on_click):
        self = objc.super(_ParticleView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = on_click
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(False)
        em = CAEmitterLayer.layer()
        em.setEmitterPosition_((WIN / 2, WIN / 2))
        em.setEmitterShape_("point")
        em.setEmitterMode_("outline")
        em.setRenderMode_("additive")                        # glowy, particles add light where they overlap
        cell = CAEmitterCell.emitterCell()
        cell.setContents_(_dot_image())
        cell.setBirthRate_(150.0)
        cell.setLifetime_(1.3)
        cell.setLifetimeRange_(0.5)
        cell.setVelocity_(28.0)
        cell.setVelocityRange_(15.0)
        cell.setEmissionRange_(math.pi * 2)                  # fly out in every direction
        cell.setScale_(0.26)
        cell.setScaleRange_(0.16)
        cell.setScaleSpeed_(-0.16)                           # shrink over life
        cell.setAlphaSpeed_(-0.85)                           # fade out (before hitting the window edge)
        cell.setSpin_(1.2)
        cell.setColor_(NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 0.6, 0.15, 1.0).CGColor())
        em.setEmitterCells_([cell])
        em.setBirthRate_(0.35)                               # idle multiplier: a gentle drizzle at rest
        self.layer().addSublayer_(em)
        self._em = em
        return self

    @objc.python_method
    def apply_level(self, v):
        v = max(0.0, min(1.0, v))
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        self._em.setBirthRate_(0.3 + 2.4 * v)                # burst more particles as you speak…
        self._em.setVelocity_(0.6 + 1.5 * v)                 # …and throw them out faster
        CATransaction.commit()

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()


_SUN = (1.0, 0.62, 0.16, 1.0)      # lion/sun accent shared by the rings + bars


# ---- rings: concentric rings that ripple outward, faster/brighter with your voice ----------------------------
class _RingsView(NSView):
    def initWithFrame_click_(self, frame, on_click):
        self = objc.super(_RingsView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = on_click
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(False)
        r = ORB / 2 * 0.6
        cx, cy = WIN / 2, WIN / 2
        col = NSColor.colorWithSRGBRed_green_blue_alpha_(*_SUN).CGColor()
        self._rings = []
        for _ in range(4):
            ring = CALayer.layer()
            ring.setFrame_(NSMakeRect(cx - r, cy - r, 2 * r, 2 * r))
            ring.setCornerRadius_(r)
            ring.setBorderWidth_(3.0)
            ring.setBorderColor_(col)
            ring.setBackgroundColor_(NSColor.clearColor().CGColor())
            self.layer().addSublayer_(ring)
            self._rings.append(ring)
        self._phase = 0.0
        return self

    @objc.python_method
    def apply_level(self, v):
        v = max(0.0, min(1.0, v))
        self._phase = (self._phase + 0.010 + 0.055 * v) % 1.0     # ripple faster as you speak
        n = len(self._rings)
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        for i, ring in enumerate(self._rings):
            f = (self._phase + i / float(n)) % 1.0                # 0..1 progress, staggered per ring
            ring.setTransform_(_scale(1.0 + 1.9 * f))             # expand outward
            ring.setOpacity_(float(max(0.0, 1.0 - f) * (0.35 + 0.65 * v)))
        CATransaction.commit()

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()


# ---- bars: a little waveform of bars that dance with your voice ----------------------------------------------
class _BarsView(NSView):
    def initWithFrame_click_(self, frame, on_click):
        self = objc.super(_BarsView, self).initWithFrame_(frame)
        if self is None:
            return None
        self._on_click = on_click
        self.setWantsLayer_(True)
        self.layer().setMasksToBounds_(False)
        n, bw, gap = 5, 8, 7
        x0 = WIN / 2 - (n * bw + (n - 1) * gap) / 2
        col = NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 0.66, 0.18, 1.0).CGColor()
        self._bars = []
        for i in range(n):
            bar = CALayer.layer()
            bar.setBackgroundColor_(col)
            bar.setCornerRadius_(bw / 2)
            bar.setFrame_(NSMakeRect(x0 + i * (bw + gap), WIN / 2 - 8, bw, 16))
            self.layer().addSublayer_(bar)
            self._bars.append((bar, x0 + i * (bw + gap), bw))
        return self

    @objc.python_method
    def apply_level(self, v):
        v = max(0.0, min(1.0, v))
        t = time.monotonic()
        cy = WIN / 2
        CATransaction.begin()
        CATransaction.setDisableActions_(True)
        for i, (bar, x, bw) in enumerate(self._bars):
            amp = (0.25 + 0.75 * v) * (0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 7.0 + i * 1.3)))
            h = 12 + amp * 66
            bar.setFrame_(NSMakeRect(x, cy - h / 2, bw, h))
        CATransaction.commit()

    def mouseDown_(self, event):
        if self._on_click:
            self._on_click()


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


STYLES = ("orb", "particles", "rings", "bars")


def view_for(style: str):
    """Map a style name to its listening-animation NSView class (shared by the app + the preview)."""
    return {"orb": _OrbView, "particles": _ParticleView, "rings": _RingsView, "bars": _BarsView}.get(style, _OrbView)


def main():
    try:
        sys.stdout.reconfigure(line_buffering=True)   # os._exit below discards a block-buffered pipe otherwise
    except Exception:
        pass
    style = next((s for s in sys.argv[1:] if s in STYLES), "orb")
    app = NSApplication.sharedApplication()
    orb = ListeningOrb.alloc().initWithOnClick_(lambda: print("clicked -> (would open chat)"))
    orb._view_cls = view_for(style)
    print(f"style: {style}   (try: " + " | ".join(f"python -m sheru.orb {k}" for k in STYLES) + ")")
    orb.show()
    threading.Thread(target=_mic_sampler, daemon=True).start()

    from Foundation import NSTimer
    t0 = time.monotonic()

    class _T(NSObject):
        _n = 0

        def tick_(self, _):
            orb.set_level(_amp["v"])
            self._n += 1
            if self._n % 30 == 0:                 # ~1x/sec: confirm the mic is actually feeding levels
                print(f"mic level: {_amp['v']:.3f}")
            if time.monotonic() - t0 > 22:        # end the preview after ~22s
                orb.hide()
                AppHelper.stopEventLoop()
    t = _T.alloc().init()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1 / 30.0, t, "tick:", None, True)
    print("orb preview: speak into the mic — it should swell with your voice. ~22s. Click it to test the tap.")
    AppHelper.runConsoleEventLoop()
    import os
    os._exit(0)             # the daemon mic-sampler holds a PortAudio stream that hangs a clean exit — force it


if __name__ == "__main__":
    main()
