"""In-app onboarding window — glassy, no terminal.

Shows Sheru's intro, each permission with a live status dot + a Grant button that opens the right pane and
re-checks itself, a location field, and what Sheru can do. Marks setup done so it won't nag next launch.
"""
from __future__ import annotations

import json
import time

import objc
from AppKit import (
    NSPanel, NSView, NSTextField, NSButton, NSColor, NSFont, NSApp, NSVisualEffectView,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered, NSFloatingWindowLevel, NSBezelStyleRounded, NSButtonTypeMomentaryPushIn,
    NSTextAlignmentLeft, NSLineBreakByWordWrapping,
)
from Foundation import NSObject, NSMakeRect, NSTimer

from . import config, permissions
from .actions import location
from .wizard import CAPABILITIES, MARKER

W, HGT = 540, 640
GREEN, RED = None, None  # set lazily (need app)


def _label(text, x, y, w, h, size=13, bold=False, color=None, dim=False):
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setStringValue_(text)
    f.setBezeled_(False); f.setDrawsBackground_(False); f.setEditable_(False); f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    f.setTextColor_(color or (NSColor.secondaryLabelColor() if dim else NSColor.labelColor()))
    f.setLineBreakMode_(NSLineBreakByWordWrapping)
    return f


class Onboarding(NSObject):
    def initWithApp_(self, app):
        self = objc.super(Onboarding, self).init()
        if self is None:
            return None
        self._app = app
        self._win = None
        self._rows = {}      # key -> (dot_label, grant_button)
        self._timer = None
        return self

    # ---- build ----
    @objc.python_method
    def _build(self):
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskFullSizeContentView
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, HGT), style, NSBackingStoreBuffered, False)
        win.setTitle_("Welcome to Sheru")
        win.setTitlebarAppearsTransparent_(True)
        win.setMovableByWindowBackground_(True)
        win.setLevel_(NSFloatingWindowLevel)

        vev = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, HGT))
        vev.setMaterial_(6)          # popover material
        vev.setBlendingMode_(0); vev.setState_(1)
        win.setContentView_(vev)

        y = HGT - 70
        vev.addSubview_(_label("🦁  Hi, I'm Sheru", 28, y, W - 56, 34, size=24, bold=True))
        y -= 30
        vev.addSubview_(_label("Your voice assistant and companion. Let's get a few permissions set up.",
                               28, y, W - 56, 20, size=13, dim=True))

        # permissions
        y -= 44
        vev.addSubview_(_label("PERMISSIONS", 28, y, 200, 18, size=11, bold=True, color=NSColor.secondaryLabelColor()))
        y -= 8
        for p in permissions.status():
            y -= 52
            dot = _label("", 28, y + 14, 22, 22, size=17)
            vev.addSubview_(dot)
            vev.addSubview_(_label(p.label, 52, y + 20, 220, 18, size=14, bold=True))
            vev.addSubview_(_label(p.why, 52, y + 2, W - 200, 18, size=11, dim=True))
            btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 130, y + 12, 100, 26))
            btn.setTitle_("Grant")
            btn.setBezelStyle_(NSBezelStyleRounded)
            btn.setButtonType_(NSButtonTypeMomentaryPushIn)
            btn.setTarget_(self); btn.setAction_("grant:")
            btn.setToolTip_(p.key)
            vev.addSubview_(btn)
            self._rows[p.key] = (dot, btn)

        # location
        y -= 62
        vev.addSubview_(_label("LOCATION", 28, y + 18, 200, 18, size=11, bold=True, color=NSColor.secondaryLabelColor()))
        loc = NSTextField.alloc().initWithFrame_(NSMakeRect(28, y - 10, W - 150, 26))
        loc.setStringValue_(location.describe() or "")
        loc.setPlaceholderString_("Your city, e.g. Ravangla, Sikkim")
        vev.addSubview_(loc); self._loc = loc
        save = NSButton.alloc().initWithFrame_(NSMakeRect(W - 118, y - 11, 90, 28))
        save.setTitle_("Save"); save.setBezelStyle_(NSBezelStyleRounded)
        save.setTarget_(self); save.setAction_("saveLocation:")
        vev.addSubview_(save)

        # capabilities
        y -= 40
        vev.addSubview_(_label("WHAT I CAN DO", 28, y, 200, 18, size=11, bold=True, color=NSColor.secondaryLabelColor()))
        caps = "\n".join("•  " + c.split("—")[0].strip() for c in CAPABILITIES)
        y -= 150
        vev.addSubview_(_label(caps, 28, y, W - 56, 150, size=12))

        # get started
        go = NSButton.alloc().initWithFrame_(NSMakeRect(W - 170, 22, 142, 34))
        go.setTitle_("Get Started"); go.setBezelStyle_(NSBezelStyleRounded)
        go.setKeyEquivalent_("\r")
        go.setTarget_(self); go.setAction_("done:")
        vev.addSubview_(go)

        win.center()
        self._win = win
        self._refresh()

    @objc.python_method
    def _refresh(self):
        for p in permissions.status():
            row = self._rows.get(p.key)
            if not row:
                continue
            dot, btn = row
            if p.status == "granted":
                dot.setStringValue_("✅"); btn.setHidden_(True)
            else:
                dot.setStringValue_("⚪️"); btn.setHidden_(False)

    # ---- show ----
    @objc.python_method
    def show(self):
        if self._win is None:
            self._build()
        NSApp.activateIgnoringOtherApps_(True)
        self._win.makeKeyAndOrderFront_(None)
        self._win.orderFrontRegardless()
        self._refresh()
        if self._timer is None:
            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                2.0, self, "tick:", None, True)

    # ---- selectors ----
    def grant_(self, sender):
        permissions.request_prompt(sender.toolTip())
        self._refresh()

    def saveLocation_(self, sender):
        val = self._loc.stringValue().strip()
        if val:
            config.update_profile("location", val)

    def tick_(self, timer):
        self._refresh()

    def done_(self, sender):
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            MARKER.write_text(json.dumps({"done": True, "ts": time.time()}))
        except Exception:
            pass
        if self._timer is not None:
            self._timer.invalidate(); self._timer = None
        self._win.orderOut_(None)
