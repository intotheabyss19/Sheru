"""'Type to Sheru' — a Spotlight-style glassy panel to type a request and see the reply silently.

Frosted-glass (NSVisualEffectView) non-activating floating panel with rounded corners, like macOS Spotlight.
Enter submits; the request runs the same pipeline as voice, output shown as text (no speech). Behaviours that
make it feel like Spotlight: it DISMISSES when you click away (resigns key), and when empty it shows your
RECENT history + actions instead of a blank box. Escape also hides it.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import objc
from AppKit import (
    NSPanel, NSTextField, NSTextView, NSScrollView, NSBox, NSColor, NSFont, NSApp, NSButton, NSView,
    NSVisualEffectView, NSAttributedString, NSFontAttributeName, NSForegroundColorAttributeName,
    NSEvent, NSEventMaskLeftMouseDown, NSEventMaskRightMouseDown,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSFloatingWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary, NSBackingStoreBuffered,
    NSFocusRingTypeNone, NSBoxSeparator,
    NSViewWidthSizable, NSViewHeightSizable,
)
from Foundation import NSMakeRect, NSMakeSize, NSObject
from PyObjCTools import AppHelper

# NSVisualEffect constants (not always exported by name in pyobjc)
_MATERIAL_HUD = 13          # NSVisualEffectMaterialHUDWindow
_MATERIAL_POPOVER = 6       # NSVisualEffectMaterialPopover
_BLEND_BEHIND = 0           # behindWindow
_STATE_ACTIVE = 1           # active

W, H, PAD, INPUT_H = 720, 540, 18, 44   # taller: it's a chat interface now, so the transcript needs room


class _Panel(NSPanel):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False


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
        self._history_provider = None      # () -> [(utterance, reply), ...] newest-first
        self._live = False                 # True while showing a live reply (so recent view doesn't clobber it)
        self._chat = []                    # chat transcript: [{role:'you'|'sheru', text, pending?}]
        self._card = None                  # Siri-style message card (NSView) while confirming a message
        self._on_send = None
        self._on_cancel = None
        self._click_mon = None             # global click-away monitor (true dismiss, no resignKey false-positives)
        self._quick = None                 # quick-actions row (NSView)
        self._sw_timer = None              # reply stopwatch NSTimer
        self._sw_t0 = None
        return self

    @objc.python_method
    def set_history_provider(self, fn):
        self._history_provider = fn

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
        p.setHidesOnDeactivate_(False)     # don't self-vanish on app-deactivate; we dismiss via a click-away monitor
        p.setAnimationBehavior_(2)         # NSWindowAnimationBehaviorNone — removes the show/hide fade that reads as flicker
        p.setReleasedWhenClosed_(False)    # the instance survives hide/show

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

        # output — transparent scrollable text (recent history when idle, the reply when live)
        sep_y = H - PAD - INPUT_H - 10
        quick_y, quick_h = 26, 26
        scroll_y = quick_y + quick_h + 4
        scroll_h = sep_y - scroll_y - 6
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(PAD, scroll_y, W - 2 * PAD, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 2 * PAD, scroll_h))
        tv.setEditable_(False)
        tv.setDrawsBackground_(False)
        tv.setFont_(NSFont.systemFontOfSize_(16))
        tv.setTextColor_(NSColor.labelColor())
        tv.setTextContainerInset_((0, 4))
        tv.setVerticallyResizable_(True)                  # grow with content so the scroll view can reach ALL of it
        tv.setHorizontallyResizable_(False)
        tv.setMinSize_(NSMakeSize(0.0, scroll_h))
        tv.setMaxSize_(NSMakeSize(1.0e7, 1.0e7))
        tv.setAutoresizingMask_(NSViewWidthSizable)
        tc = tv.textContainer()
        tc.setContainerSize_(NSMakeSize(W - 2 * PAD, 1.0e7))
        tc.setWidthTracksTextView_(True)
        scroll.setDocumentView_(tv)
        vev.addSubview_(scroll)
        self._out = tv

        # quick-actions row — one-tap shortcuts for the most common commands
        quick = NSView.alloc().initWithFrame_(NSMakeRect(PAD, quick_y, W - 2 * PAD, quick_h))
        bx = 0
        for title, cmd in (("🌤 Weather", "what's the weather"), ("⏸ Pause", "pause"),
                           ("⏭ Next", "next"), ("⏱ 10 min", "set a timer for 10 minutes"),
                           ("📰 News", "what's the news")):
            bw = 118
            b = NSButton.alloc().initWithFrame_(NSMakeRect(bx, 0, bw, quick_h))
            b.setTitle_(title); b.setBezelStyle_(1); b.setFont_(NSFont.systemFontOfSize_(12))
            b.setToolTip_(cmd)                 # carries the command string for quickTap_
            b.setTarget_(self); b.setAction_("quickTap:")
            quick.addSubview_(b)
            bx += bw + 6
        vev.addSubview_(quick)
        self._quick = quick

        # status line (local vs Claude + stopwatch)
        st = NSTextField.alloc().initWithFrame_(NSMakeRect(PAD, 6, W - 2 * PAD, 16))
        st.setBezeled_(False); st.setDrawsBackground_(False); st.setEditable_(False); st.setSelectable_(False)
        st.setFont_(NSFont.systemFontOfSize_(11)); st.setTextColor_(NSColor.secondaryLabelColor())
        st.setStringValue_("")
        vev.addSubview_(st); self._status = st

        p.center()
        self._panel = p

    # ---- attributed-text helpers for the recent list --------------------------------
    @objc.python_method
    def _attr(self, text, color, size, weight=None):
        font = NSFont.systemFontOfSize_(size) if weight is None else NSFont.systemFontOfSize_weight_(size, weight)
        return NSAttributedString.alloc().initWithString_attributes_(
            text, {NSFontAttributeName: font, NSForegroundColorAttributeName: color})

    @objc.python_method
    def _seed_chat(self):
        """First open: seed the transcript from recent history so past turns show as chat."""
        if not self._chat and self._history_provider is not None:
            try:
                for u, r in reversed(self._history_provider() or []):   # provider is newest-first; chat wants oldest-first
                    self._chat.append({"role": "you", "text": u})
                    if r:
                        self._chat.append({"role": "sheru", "text": r})
            except Exception:
                pass

    @objc.python_method
    def _render_chat(self):
        """Render the conversation as a chat flow — You (what Sheru heard) + Sheru (its reply)."""
        ts = self._out.textStorage()
        ts.beginEditing()
        ts.setAttributedString_(NSAttributedString.alloc().initWithString_(""))
        if not self._chat:
            ts.appendAttributedString_(self._attr("Type a command, or tap the mic and speak.\n\n",
                                                  NSColor.secondaryLabelColor(), 15))
            ts.appendAttributedString_(self._attr("Try (one clear sentence works best):\n",
                                                  NSColor.tertiaryLabelColor(), 12))
            for ex in ("“message Piyush on WhatsApp that I'm running late”",
                       "“play Dandelions”     “what's the weather”",
                       "“set an alarm for quarter past seven”",
                       "“ask Claude to summarize this PDF”"):
                ts.appendAttributedString_(self._attr("   " + ex + "\n",
                                                      NSColor.secondaryLabelColor(), 13))
        for turn in self._chat:
            you = turn["role"] == "you"
            ts.appendAttributedString_(self._attr(("You   " if you else "Sheru   "),
                                                  NSColor.systemBlueColor() if you else NSColor.tertiaryLabelColor(), 11))
            ts.appendAttributedString_(self._attr((turn.get("text") or "…") + "\n",
                                                  NSColor.labelColor() if you else NSColor.secondaryLabelColor(), 15))
            ts.appendAttributedString_(self._attr("\n", NSColor.clearColor(), 3))
        ts.endEditing()
        self._out.scrollRangeToVisible_((len(self._out.string()), 0))   # keep newest in view

    @objc.python_method
    def push_user(self, text: str):
        """Show what Sheru heard (voice) or what you typed, then a pending Sheru turn to fill with the reply."""
        def do():
            self._live = True
            self._clear_card()
            self._chat.append({"role": "you", "text": text})
            self._chat.append({"role": "sheru", "text": "…", "pending": True})
            if len(self._chat) > 40:
                del self._chat[: len(self._chat) - 40]
            self._render_chat()
            self._sw_start()          # start the reply stopwatch (shows "⏳ Ns" until the reply lands)
        AppHelper.callAfter(do)

    @objc.python_method
    def show(self):
        if self._panel is None:
            self._build()
        self._live = False
        self._clear_card()
        self._field.setStringValue_("")
        self._seed_chat()
        self._render_chat()
        NSApp.activateIgnoringOtherApps_(True)
        self._panel.makeKeyAndOrderFront_(None)
        self._panel.orderFrontRegardless()
        self._panel.makeFirstResponder_(self._field)
        self._install_click_monitor()        # dismiss on a real click in another app (no resignKey false-positives)

    @objc.python_method
    def hide(self):
        self._remove_click_monitor()
        if self._panel is not None:
            self._panel.orderOut_(None)

    # click-away dismiss via a GLOBAL mouse-down monitor — fires only for clicks in OTHER apps (true click-away),
    # never for our own subviews or the activation churn that made windowDidResignKey_ flash the panel.
    @objc.python_method
    def _install_click_monitor(self):
        if self._click_mon is not None:
            return
        self._click_mon = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown, lambda e: self.hide())

    @objc.python_method
    def _remove_click_monitor(self):
        if self._click_mon is not None:
            NSEvent.removeMonitor_(self._click_mon)
            self._click_mon = None

    @objc.python_method
    def is_visible(self):
        return self._panel is not None and self._panel.isVisible()

    # ---- Siri-style message card (recipient + bubble + Send/Cancel) ------------------
    @objc.python_method
    def show_message_card(self, recipient, text, on_send, on_cancel):
        def do():
            if self._panel is None:
                return
            self._live = True
            self._clear_card()
            self._on_send, self._on_cancel = on_send, on_cancel
            top = H - PAD - INPUT_H - 24
            bottom = PAD + 6
            ch = top - bottom
            cw = W - 2 * PAD
            card = NSView.alloc().initWithFrame_(NSMakeRect(PAD, bottom, cw, ch))
            card.setWantsLayer_(True)

            to = NSTextField.alloc().initWithFrame_(NSMakeRect(4, ch - 26, cw - 8, 20))
            to.setBezeled_(False); to.setDrawsBackground_(False); to.setEditable_(False); to.setSelectable_(False)
            to.setFont_(NSFont.systemFontOfSize_(13)); to.setTextColor_(NSColor.secondaryLabelColor())
            to.setStringValue_("To  " + (recipient or ""))
            card.addSubview_(to)

            bh = ch - 26 - 8 - 46
            bubble = NSView.alloc().initWithFrame_(NSMakeRect(0, 48, cw, bh))
            bubble.setWantsLayer_(True)
            bubble.layer().setCornerRadius_(14.0)
            bubble.layer().setBackgroundColor_(NSColor.systemBlueColor().colorWithAlphaComponent_(0.90).CGColor())
            msg = NSTextField.alloc().initWithFrame_(NSMakeRect(14, 8, cw - 28, bh - 16))
            msg.setBezeled_(False); msg.setDrawsBackground_(False); msg.setEditable_(False); msg.setSelectable_(True)
            msg.setFont_(NSFont.systemFontOfSize_(17)); msg.setTextColor_(NSColor.whiteColor())
            msg.setUsesSingleLineMode_(False); msg.cell().setWraps_(True); msg.cell().setLineBreakMode_(0)
            msg.setStringValue_(text or "")
            bubble.addSubview_(msg)
            card.addSubview_(bubble)

            send = NSButton.alloc().initWithFrame_(NSMakeRect(cw - 104, 6, 104, 32))
            send.setTitle_("Send"); send.setBezelStyle_(1); send.setKeyEquivalent_("\r")
            send.setTarget_(self); send.setAction_("cardSend:")
            card.addSubview_(send)
            cancel = NSButton.alloc().initWithFrame_(NSMakeRect(cw - 104 - 96, 6, 92, 32))
            cancel.setTitle_("Cancel"); cancel.setBezelStyle_(1)
            cancel.setTarget_(self); cancel.setAction_("cardCancel:")
            card.addSubview_(cancel)

            sv = self._out.enclosingScrollView()
            if sv is not None:
                sv.setHidden_(True)
            if self._quick is not None:
                self._quick.setHidden_(True)         # don't let shortcut chips peek through the message card
            self._panel.contentView().addSubview_(card)
            self._card = card
        AppHelper.callAfter(do)

    @objc.python_method
    def _clear_card(self):
        if getattr(self, "_card", None) is not None:
            self._card.removeFromSuperview()
            self._card = None
        sv = self._out.enclosingScrollView() if getattr(self, "_out", None) is not None else None
        if sv is not None:
            sv.setHidden_(False)
        if getattr(self, "_quick", None) is not None:
            self._quick.setHidden_(False)

    def cardSend_(self, sender):
        cb = self._on_send
        self._clear_card()
        if cb:
            cb()

    def cardCancel_(self, sender):
        cb = self._on_cancel
        self._clear_card()
        if cb:
            cb()

    @objc.python_method
    def set_status(self, text: str):
        def do():
            if getattr(self, "_status", None) is not None:
                self._status.setStringValue_(text)
        AppHelper.callAfter(do)

    @objc.python_method
    def _set_out(self, text: str):
        def do():
            self._live = True
            self._sw_stop()
            self._clear_card()
            self._out.setString_(text)
            self._out.scrollRangeToVisible_((len(self._out.string()), 0))
        AppHelper.callAfter(do)

    @objc.python_method
    def _append(self, text: str):
        def do():
            self._live = True
            self._sw_stop()
            self._clear_card()
            if self._chat and self._chat[-1]["role"] == "sheru":
                t = self._chat[-1]
                if t.get("pending"):
                    t["text"] = text; t["pending"] = False
                else:
                    t["text"] = t["text"] + (" " if t["text"] and not t["text"].endswith((" ", "\n")) else "") + text
            else:
                self._chat.append({"role": "sheru", "text": text})
            self._render_chat()
        AppHelper.callAfter(do)

    # ---- reply stopwatch (an at-a-glance "how long is this taking") ------------------
    @objc.python_method
    def _sw_start(self):
        if not self.is_visible():
            return
        from Foundation import NSTimer
        self._sw_stop()
        self._sw_t0 = time.monotonic()
        self._sw_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "swTick:", None, True)

    def swTick_(self, timer):
        if self._sw_t0 is None or not self.is_visible():
            self._sw_stop(); return
        if getattr(self, "_status", None) is not None:
            self._status.setStringValue_("⏳ %.1fs" % (time.monotonic() - self._sw_t0))

    @objc.python_method
    def _sw_stop(self):
        if self._sw_timer is not None:
            self._sw_timer.invalidate(); self._sw_timer = None
        self._sw_t0 = None
        # only clear OUR stopwatch text — never stomp the app's "☁️ Claude · Ns" progress line
        if getattr(self, "_status", None) is not None and self._status.stringValue().startswith("⏳"):
            self._status.setStringValue_("")

    # ---- submit (Enter or a quick-action chip) --------------------------------------
    @objc.python_method
    def _submit(self, text: str):
        """Show the utterance, then route it OFF the main thread so the UI stays live during Claude calls."""
        self.push_user(text)
        threading.Thread(target=lambda: self._on_submit(text, self._append), daemon=True).start()

    def quickTap_(self, sender):
        cmd = sender.toolTip()
        if cmd:
            self._submit(cmd)

    def micPressed_(self, sender):
        if self._on_mic is not None:
            self._on_mic()

    # NSTextField delegate: Enter submits, Esc hides
    def control_textView_doCommandBySelector_(self, control, textView, selector):
        if selector == "insertNewline:":
            text = self._field.stringValue().strip()
            if text:
                self._field.setStringValue_("")
                self._submit(text)
            return True
        if selector == "cancelOperation:":
            self.hide()
            return True
        return False
