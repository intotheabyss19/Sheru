"""'Type to Sheru' — a Spotlight-style glassy panel to type a request and see the reply silently.

Frosted-glass (NSVisualEffectView) non-activating floating panel with rounded corners, like macOS system
UI. Enter submits; the request runs through the same pipeline as voice, output shown as text (no speech).
Escape hides it.
"""
from __future__ import annotations

from typing import Callable

import objc
from AppKit import (
    NSPanel, NSTextField, NSTextView, NSScrollView, NSBox, NSColor, NSFont, NSApp, NSButton,
    NSVisualEffectView,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSFloatingWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary, NSBackingStoreBuffered,
    NSFocusRingTypeNone, NSBoxSeparator,
    NSViewWidthSizable, NSViewHeightSizable,
)
from Foundation import NSMakeRect, NSObject
from PyObjCTools import AppHelper

# NSVisualEffect constants (not always exported by name in pyobjc)
_MATERIAL_HUD = 13          # NSVisualEffectMaterialHUDWindow
_MATERIAL_POPOVER = 6       # NSVisualEffectMaterialPopover
_BLEND_BEHIND = 0           # behindWindow
_STATE_ACTIVE = 1           # active

W, H, PAD, INPUT_H = 660, 260, 18, 44


class _Panel(NSPanel):
    def canBecomeKeyWindow(self):
        return True


class TypePanel(NSObject):
    """Owns the panel; call show(). `on_submit(text, sink)` routes the request; sink appends reply text."""

    def initWithSubmit_(self, on_submit: Callable):
        return self.initWithSubmit_onMic_(on_submit, None)

    def initWithSubmit_onMic_(self, on_submit: Callable, on_mic):
        self = objc.super(TypePanel, self).init()
        if self is None:
            return None
        self._on_submit = on_submit
        self._on_mic = on_mic
        self._panel = None
        return self

    @objc.python_method
    def _build(self):
        style = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        p = _Panel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False)
        p.setLevel_(NSFloatingWindowLevel)
        p.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces
                                 | NSWindowCollectionBehaviorStationary)
        p.setOpaque_(False)
        p.setBackgroundColor_(NSColor.clearColor())
        p.setHasShadow_(True)
        p.setMovableByWindowBackground_(True)

        # frosted-glass backing with rounded corners
        vev = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        vev.setMaterial_(_MATERIAL_HUD)
        vev.setBlendingMode_(_BLEND_BEHIND)
        vev.setState_(_STATE_ACTIVE)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(16.0)
        vev.layer().setMasksToBounds_(True)
        vev.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        p.setContentView_(vev)

        # input field — borderless, transparent, large (Spotlight-like)
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(PAD, H - PAD - INPUT_H, W - 2 * PAD - 46, INPUT_H))
        field.setFont_(NSFont.systemFontOfSize_(24))
        field.setPlaceholderString_("Type to Sheru…")
        field.setBordered_(False)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setFocusRingType_(NSFocusRingTypeNone)
        field.setTextColor_(NSColor.labelColor())
        field.setDelegate_(self)
        vev.addSubview_(field)
        self._field = field

        mic = NSButton.alloc().initWithFrame_(NSMakeRect(W - PAD - 40, H - PAD - INPUT_H + 2, 40, INPUT_H - 4))
        mic.setTitle_("🎙")
        mic.setBordered_(False)
        mic.setFont_(NSFont.systemFontOfSize_(22))
        mic.setTarget_(self)
        mic.setAction_("micPressed:")
        mic.setToolTip_("Listen (or press F5)")
        vev.addSubview_(mic)

        # separator
        sep = NSBox.alloc().initWithFrame_(NSMakeRect(PAD, H - PAD - INPUT_H - 10, W - 2 * PAD, 1))
        sep.setBoxType_(NSBoxSeparator)
        vev.addSubview_(sep)

        # output — transparent scrollable text
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(PAD, PAD + 14, W - 2 * PAD, H - 2 * PAD - INPUT_H - 34))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 2 * PAD, H - 2 * PAD - INPUT_H - 20))
        tv.setEditable_(False)
        tv.setDrawsBackground_(False)
        tv.setFont_(NSFont.systemFontOfSize_(16))
        tv.setTextColor_(NSColor.labelColor())
        tv.setTextContainerInset_((0, 4))
        scroll.setDocumentView_(tv)
        vev.addSubview_(scroll)
        self._out = tv

        # status line (local vs Claude + stopwatch)
        st = NSTextField.alloc().initWithFrame_(NSMakeRect(PAD, 6, W - 2 * PAD, 16))
        st.setBezeled_(False); st.setDrawsBackground_(False); st.setEditable_(False); st.setSelectable_(False)
        st.setFont_(NSFont.systemFontOfSize_(11)); st.setTextColor_(NSColor.secondaryLabelColor())
        st.setStringValue_("")
        vev.addSubview_(st); self._status = st

        p.center()
        self._panel = p

    @objc.python_method
    def show(self):
        if self._panel is None:
            self._build()
        self._out.setString_("")
        self._field.setStringValue_("")
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
        self._panel.makeFirstResponder_(self._field)

    @objc.python_method
    def hide(self):
        if self._panel is not None:
            self._panel.orderOut_(None)

    @objc.python_method
    def set_status(self, text: str):
        def do():
            if getattr(self, "_status", None) is not None:
                self._status.setStringValue_(text)
        AppHelper.callAfter(do)

    @objc.python_method
    def _set_out(self, text: str):
        def do():
            self._out.setString_(text)
            self._out.scrollRangeToVisible_((len(self._out.string()), 0))
        AppHelper.callAfter(do)

    @objc.python_method
    def _append(self, text: str):
        def do():
            cur = self._out.string()
            cur = "" if cur == "…" else cur
            self._out.setString_((cur + (" " if cur and not cur.endswith((" ", "\n")) else "") + text))
            self._out.scrollRangeToVisible_((len(self._out.string()), 0))
        AppHelper.callAfter(do)

    def micPressed_(self, sender):
        if self._on_mic is not None:
            self._on_mic()

    # NSTextField delegate: Enter submits, Esc hides
    def control_textView_doCommandBySelector_(self, control, textView, selector):
        if selector == "insertNewline:":
            text = self._field.stringValue().strip()
            if text:
                self._field.setStringValue_("")
                self._set_out("…")
                self._on_submit(text, self._append)
            return True
        if selector == "cancelOperation:":
            self.hide()
            return True
        return False
