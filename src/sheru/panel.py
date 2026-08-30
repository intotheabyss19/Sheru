"""'Type to Sheru' — a glassy floating chat panel: type a request, see the reply as iMessage-style bubbles.

Frosted-glass (NSVisualEffectView) non-activating panel, rounded corners, Spotlight-style top input. The
conversation renders as real bubbles in a flipped scroll view: your turns are warm gold gradient bubbles on
the right; Sheru's are tinted bubbles on the left — GOLD when handled on-device (⚡) or BLUE when it went to
Claude (☁️), the whole point being you can see at a glance where the work happened. Comfortable spacing,
subtle per-turn timestamps, animated typing dots + elapsed time while a reply is in flight.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

import objc
from AppKit import (
    NSPanel, NSTextField, NSScrollView, NSBox, NSColor, NSFont, NSApp, NSButton, NSView,
    NSVisualEffectView, NSAttributedString, NSMutableAttributedString, NSSearchField,
    NSFontAttributeName, NSForegroundColorAttributeName,
    NSEvent, NSEventMaskLeftMouseDown, NSEventMaskRightMouseDown,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSFloatingWindowLevel, NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary, NSBackingStoreBuffered,
    NSFocusRingTypeNone, NSBoxSeparator, NSImage, NSImageView,
    NSViewWidthSizable, NSViewHeightSizable, NSViewMinYMargin,
    NSLineBreakByWordWrapping, NSTextAlignmentRight, NSTextAlignmentLeft,
)
from Foundation import NSMakeRect, NSMakeSize, NSMakePoint, NSObject
from PyObjCTools import AppHelper

# NSVisualEffect constants (not always exported by name in pyobjc)
_MATERIAL_HUD = 13          # NSVisualEffectMaterialHUDWindow
_BLEND_BEHIND = 0           # behindWindow
_STATE_ACTIVE = 1           # active
_USES_LINE_FRAGMENT = 1     # NSStringDrawingUsesLineFragmentOrigin

W, H, PAD, INPUT_H = 820, 620, 20, 46          # a bit larger for comfortable bubbles

# ---- lion gold / amber palette --------------------------------------------------------------------
def _rgba(r, g, b, a=1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(r, g, b, a)

GOLD = _rgba(0.98, 0.62, 0.09)                 # amber, the accent
GOLD_HI = _rgba(1.00, 0.74, 0.20)              # lighter amber (gradient top)
GOLD_LO = _rgba(0.92, 0.47, 0.05)              # deeper orange (gradient bottom)
LOCAL_TINT = _rgba(0.98, 0.62, 0.09, 0.20)     # on-device Sheru bubble fill
LOCAL_EDGE = _rgba(0.98, 0.62, 0.09, 0.55)
CLAUDE_TINT = _rgba(0.30, 0.62, 1.00, 0.20)    # Claude Sheru bubble fill
CLAUDE_EDGE = _rgba(0.30, 0.62, 1.00, 0.55)

# comfortable density
FONT_MSG = 15.5
PADX, PADY = 14, 10                             # inside-bubble padding
GAP = 16                                        # between turns
META_H = 16                                     # sender/timestamp row height
TOP_PAD, BOT_PAD = 8, 10


class _Panel(NSPanel):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return False


class _Flipped(NSView):
    """Top-left origin so bubbles stack naturally top→bottom."""
    def isFlipped(self):
        return True


def _measure(text, font, maxw):
    attr = NSAttributedString.alloc().initWithString_attributes_(text, {NSFontAttributeName: font})
    rect = attr.boundingRectWithSize_options_(NSMakeSize(maxw, 1.0e6), _USES_LINE_FRAGMENT)
    return rect.size.width, rect.size.height


def _fmt_time(ts):
    if not ts:
        return ""
    lt = time.localtime(ts)
    h = lt.tm_hour % 12 or 12
    return f"{h}:{lt.tm_min:02d}"


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
        self._history_provider = None
        self._live = False
        self._chat = []                    # [{role:'you'|'sheru', text, pending?, src, ts}]
        self._card = None
        self._on_send = None
        self._on_cancel = None
        self._click_mon = None
        self._quick = None
        self._sw_timer = None
        self._sw_t0 = None
        self._dots = 0                     # animation phase for typing dots
        self._next_src = "local"
        self._hist = None                  # history overlay view
        self._hist_provider = None         # (query) -> [session dicts]
        self._hist_open = None             # (id) -> load that conversation
        self._hist_star = None             # (id) -> toggle star, returns new state
        self._hist_search = None
        self._hist_doc = None
        self._viewing = False              # True while viewing a past conversation
        return self

    @objc.python_method
    def set_source(self, src):
        self._next_src = src

    @objc.python_method
    def set_history_provider(self, fn):
        self._history_provider = fn

    # ---- build ----------------------------------------------------------------------
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
        p.setHidesOnDeactivate_(False)
        p.setAnimationBehavior_(2)
        p.setReleasedWhenClosed_(False)

        vev = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
        vev.setMaterial_(_MATERIAL_HUD)
        vev.setBlendingMode_(_BLEND_BEHIND)
        vev.setState_(_STATE_ACTIVE)
        vev.setWantsLayer_(True)
        vev.layer().setCornerRadius_(18.0)
        vev.layer().setMasksToBounds_(True)
        vev.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        p.setContentView_(vev)

        # history button — top-left, opens the past-conversations browser (mirrors the mic top-right)
        hist = NSButton.alloc().initWithFrame_(NSMakeRect(PAD, H - PAD - INPUT_H + 4, 34, INPUT_H - 8))
        hist.setBordered_(False)
        hist.setTitle_("")
        hist.setImagePosition_(2)
        himg = self._symbol("clock.arrow.circlepath", 19)
        if himg is not None:
            hist.setImage_(himg)
        else:
            hist.setImagePosition_(0); hist.setTitle_("🕘"); hist.setFont_(NSFont.systemFontOfSize_(19))
        hist.setContentTintColor_(NSColor.secondaryLabelColor())
        hist.setTarget_(self); hist.setAction_("historyPressed:")
        hist.setToolTip_("Past conversations")
        hist.setAutoresizingMask_(NSViewMinYMargin)
        vev.addSubview_(hist)
        self._histbtn = hist

        # input field — borderless, transparent, large (Spotlight-like)
        field = NSTextField.alloc().initWithFrame_(NSMakeRect(PAD + 42, H - PAD - INPUT_H, W - 2 * PAD - 52 - 42, INPUT_H))
        field.setFont_(NSFont.systemFontOfSize_(25))
        field.setPlaceholderString_("Type to Sheru…")
        field.setBordered_(False)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setFocusRingType_(NSFocusRingTypeNone)
        field.setTextColor_(NSColor.labelColor())
        field.setDelegate_(self)
        field.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        vev.addSubview_(field)
        self._field = field

        # mic — monochrome SF Symbol, gold glow while listening
        mic = NSButton.alloc().initWithFrame_(NSMakeRect(W - PAD - 40, H - PAD - INPUT_H + 3, 40, INPUT_H - 6))
        mic.setBordered_(False)
        mic.setTitle_("")                       # kill the default "Button" title
        mic.setImagePosition_(2)                # NSImageOnly
        img = self._symbol("mic.fill", 20)
        if img is not None:
            mic.setImage_(img)
        else:
            mic.setImagePosition_(0)            # NSNoImage
            mic.setTitle_("🎙"); mic.setFont_(NSFont.systemFontOfSize_(21))
        mic.setContentTintColor_(NSColor.secondaryLabelColor())
        mic.setTarget_(self)
        mic.setAction_("micPressed:")
        mic.setToolTip_("Listen (or press F5)")
        mic.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)  # keep pinned top-right
        # keep it glued to the right edge on resize
        mic.setAutoresizingMask_(1 << 0 | NSViewMinYMargin)              # NSViewMinXMargin|MinYMargin
        vev.addSubview_(mic)
        self._mic = mic

        sep = NSBox.alloc().initWithFrame_(NSMakeRect(PAD, H - PAD - INPUT_H - 12, W - 2 * PAD, 1))
        sep.setBoxType_(NSBoxSeparator)
        sep.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        vev.addSubview_(sep)

        # conversation — flipped document view in a transparent scroll view
        sep_y = H - PAD - INPUT_H - 12
        quick_y, quick_h = 30, 30
        scroll_y = quick_y + quick_h + 6
        scroll_h = sep_y - scroll_y - 8
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(PAD, scroll_y, W - 2 * PAD, scroll_h))
        scroll.setHasVerticalScroller_(True)
        scroll.setAutohidesScrollers_(True)
        scroll.setDrawsBackground_(False)
        scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        doc = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, W - 2 * PAD, scroll_h))
        doc.setAutoresizingMask_(NSViewWidthSizable)
        scroll.setDocumentView_(doc)
        vev.addSubview_(scroll)
        self._scroll = scroll
        self._doc = doc

        # quick-actions row — clean rounded chips
        quick = NSView.alloc().initWithFrame_(NSMakeRect(PAD, quick_y, W - 2 * PAD, quick_h))
        quick.setAutoresizingMask_(NSViewWidthSizable)
        chips = (("Weather", "☀︎", "what's the weather"), ("Pause", "⏸", "pause"),
                 ("Next", "⏭", "next"), ("10 min", "⏱", "set a timer for 10 minutes"),
                 ("News", "📰", "what's the news"))
        bw = 150
        bx = 0
        for label, icon, cmd in chips:
            b = self._chip(NSMakeRect(bx, 0, bw, quick_h), f"{icon}  {label}", cmd)
            quick.addSubview_(b)
            bx += bw + 8
        vev.addSubview_(quick)
        self._quick = quick

        # status line (source + stopwatch), bottom
        st = NSTextField.alloc().initWithFrame_(NSMakeRect(PAD, 8, W - 2 * PAD, 16))
        st.setBezeled_(False); st.setDrawsBackground_(False); st.setEditable_(False); st.setSelectable_(False)
        st.setFont_(NSFont.systemFontOfSize_(11)); st.setTextColor_(NSColor.tertiaryLabelColor())
        st.setStringValue_("")
        st.setAutoresizingMask_(NSViewWidthSizable)
        vev.addSubview_(st); self._status = st

        p.center()
        self._panel = p

    @objc.python_method
    def _symbol(self, name, size):
        try:
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        except Exception:
            return None
        if img is None:
            return None
        try:
            from AppKit import NSImageSymbolConfiguration
            cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, 0.3)  # medium-ish
            c = img.imageWithSymbolConfiguration_(cfg)
            if c is not None:
                img = c
        except Exception:
            pass
        img.setTemplate_(True)          # template = contentTintColor (gold-when-live) applies
        return img

    @objc.python_method
    def _chip(self, frame, title, cmd):
        b = NSButton.alloc().initWithFrame_(frame)
        b.setTitle_(title)
        b.setBezelStyle_(1)
        b.setBordered_(False)
        b.setWantsLayer_(True)
        b.setFont_(NSFont.systemFontOfSize_(12.5))
        b.layer().setCornerRadius_(frame.size.height / 2.0)
        b.layer().setBackgroundColor_(_rgba(1, 1, 1, 0.08).CGColor())
        b.layer().setBorderWidth_(1.0)
        b.layer().setBorderColor_(_rgba(1, 1, 1, 0.10).CGColor())
        b.setContentTintColor_(NSColor.labelColor())
        b.setToolTip_(cmd)
        b.setTarget_(self); b.setAction_("quickTap:")
        return b

    # ---- bubble rendering -----------------------------------------------------------
    @objc.python_method
    def _meta_label(self, text, color, x, y, w, align):
        lb = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, META_H))
        lb.setBezeled_(False); lb.setDrawsBackground_(False); lb.setEditable_(False); lb.setSelectable_(False)
        lb.setFont_(NSFont.systemFontOfSize_(11))
        lb.setTextColor_(color)
        lb.setStringValue_(text)
        lb.setAlignment_(align)
        return lb

    @objc.python_method
    def _bubble(self, text, kind, maxbw):
        """kind: 'you' | 'local' | 'claude'. Returns (view, width, height)."""
        font = NSFont.systemFontOfSize_(FONT_MSG)
        s = text or "…"
        content_w = maxbw - 2 * PADX
        nat_w, _ = _measure(s, font, 1.0e5)                 # natural one-line width
        tw = min(nat_w + 8, content_w) if nat_w <= content_w else content_w   # +8 slack so it never clips
        _, th = _measure(s, font, tw)
        import math
        tw = max(math.ceil(tw), 24)
        th = math.ceil(th) + 2
        bw = tw + 2 * PADX
        bh = th + 2 * PADY
        view = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, bw, bh))
        view.setWantsLayer_(True)
        view.layer().setCornerRadius_(16.0)
        if kind == "you":
            try:
                from Quartz import CAGradientLayer
                g = CAGradientLayer.layer()
                g.setFrame_(view.bounds())
                g.setColors_([GOLD_HI.CGColor(), GOLD_LO.CGColor()])
                g.setCornerRadius_(16.0)
                view.layer().addSublayer_(g)
            except Exception:
                view.layer().setBackgroundColor_(GOLD.CGColor())
            tcolor = NSColor.whiteColor()
        else:
            fill = LOCAL_TINT if kind == "local" else CLAUDE_TINT
            edge = LOCAL_EDGE if kind == "local" else CLAUDE_EDGE
            view.layer().setBackgroundColor_(fill.CGColor())
            view.layer().setBorderWidth_(1.0)
            view.layer().setBorderColor_(edge.CGColor())
            tcolor = _rgba(0.96, 0.96, 0.97)               # explicit bright text — consistent on gold & blue tints
        lbl = NSTextField.alloc().initWithFrame_(NSMakeRect(PADX, PADY, tw, th))
        lbl.setBezeled_(False); lbl.setDrawsBackground_(False); lbl.setEditable_(False); lbl.setSelectable_(True)
        lbl.setFont_(font); lbl.setTextColor_(tcolor)
        lbl.setStringValue_(s)
        lbl.setMaximumNumberOfLines_(0)
        lbl.cell().setWraps_(True); lbl.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        lbl.cell().setTruncatesLastVisibleLine_(False)
        lbl.setAlignment_(NSTextAlignmentLeft)
        view.addSubview_(lbl)
        return view, bw, bh

    @objc.python_method
    def _render_chat(self):
        doc = self._doc
        for v in list(doc.subviews()):
            v.removeFromSuperview()
        cw = doc.frame().size.width
        maxbw = cw * 0.72
        y = TOP_PAD

        if not self._chat:
            hint = self._meta_label("Type a command, or tap the mic and speak.", NSColor.secondaryLabelColor(),
                                    0, y, cw, NSTextAlignmentLeft)
            hint.setFont_(NSFont.systemFontOfSize_(14))
            doc.addSubview_(hint)
            y += 26

        for turn in self._chat:
            you = turn["role"] == "you"
            tstr = _fmt_time(turn.get("ts"))
            if you:
                view, bw, bh = self._bubble(turn.get("text") or "", "you", maxbw)
                view.setFrame_(NSMakeRect(cw - bw, y, bw, bh))
                doc.addSubview_(view)
                y += bh + 2
                if tstr:
                    doc.addSubview_(self._meta_label(tstr, NSColor.tertiaryLabelColor(),
                                                     cw - 80, y, 78, NSTextAlignmentRight))
                    y += META_H
                y += GAP
            else:
                src = turn.get("src") or "local"
                gold = src != "claude"
                badge = "⚡" if gold else "☁︎"
                name = f"{badge}  Sheru"
                nlbl = self._meta_label(name, GOLD if gold else _rgba(0.30, 0.62, 1.0),
                                        0, y, 120, NSTextAlignmentLeft)
                nlbl.setFont_(NSFont.systemFontOfSize_weight_(11, 0.3))
                doc.addSubview_(nlbl)
                if tstr:
                    doc.addSubview_(self._meta_label(tstr, NSColor.tertiaryLabelColor(),
                                                     120, y, 80, NSTextAlignmentLeft))
                y += META_H + 2
                if turn.get("pending"):
                    dots = ("•  •  •", "•  •", "•", "•  •  •")[self._dots % 4]
                    view, bw, bh = self._bubble(dots, "local" if gold else "claude", maxbw)
                else:
                    view, bw, bh = self._bubble(turn.get("text") or "…", "local" if gold else "claude", maxbw)
                view.setFrame_(NSMakeRect(0, y, bw, bh))
                doc.addSubview_(view)
                y += bh + GAP

        total = y + BOT_PAD
        vis_h = self._scroll.contentSize().height
        doc.setFrameSize_(NSMakeSize(cw, max(total, vis_h)))
        doc.scrollRectToVisible_(NSMakeRect(0, max(total, vis_h) - 1, 1, 1))

    # ---- transcript state -----------------------------------------------------------
    @objc.python_method
    def _seed_chat(self):
        if not self._chat and self._history_provider is not None:
            try:
                for u, r in reversed(self._history_provider() or []):
                    self._chat.append({"role": "you", "text": u, "ts": None})
                    if r:
                        self._chat.append({"role": "sheru", "text": r, "ts": None})
            except Exception:
                pass

    @objc.python_method
    def push_user(self, text: str):
        def do():
            self._live = True
            self._clear_card()
            now = time.time()
            self._chat.append({"role": "you", "text": text, "ts": now})
            self._chat.append({"role": "sheru", "text": "", "pending": True, "src": self._next_src, "ts": now})
            if len(self._chat) > 40:
                del self._chat[: len(self._chat) - 40]
            self._render_chat()
            self._sw_start()
        AppHelper.callAfter(do)

    @objc.python_method
    def _append(self, text: str):
        def do():
            self._live = True
            self._sw_stop()
            self._clear_card()
            if self._chat and self._chat[-1]["role"] == "sheru":
                t = self._chat[-1]
                t["src"] = self._next_src
                if t.get("pending"):
                    t["text"] = text; t["pending"] = False
                else:
                    t["text"] = t["text"] + (" " if t["text"] and not t["text"].endswith((" ", "\n")) else "") + text
                t["ts"] = t.get("ts") or time.time()
            else:
                self._chat.append({"role": "sheru", "text": text, "src": self._next_src, "ts": time.time()})
            self._render_chat()
        AppHelper.callAfter(do)

    @objc.python_method
    def _set_out(self, text: str):
        def do():
            self._live = True
            self._sw_stop()
            self._clear_card()
            self._chat.append({"role": "sheru", "text": text, "src": self._next_src, "ts": time.time()})
            self._render_chat()
        AppHelper.callAfter(do)

    # ---- show / hide ----------------------------------------------------------------
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
        self._install_click_monitor()

    @objc.python_method
    def hide(self):
        self._remove_click_monitor()
        if self._panel is not None:
            self._panel.orderOut_(None)

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

    # ---- message card (recipient + bubble + Send/Cancel) ----------------------------
    @objc.python_method
    def show_message_card(self, recipient, text, on_send, on_cancel):
        def do():
            if self._panel is None:
                return
            self._live = True
            self._clear_card()
            self._on_send, self._on_cancel = on_send, on_cancel
            top = H - PAD - INPUT_H - 26
            bottom = PAD + 8
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
            bubble.layer().setCornerRadius_(16.0)
            try:
                from Quartz import CAGradientLayer
                g = CAGradientLayer.layer(); g.setFrame_(bubble.bounds())
                g.setColors_([GOLD_HI.CGColor(), GOLD_LO.CGColor()]); g.setCornerRadius_(16.0)
                bubble.layer().addSublayer_(g)
            except Exception:
                bubble.layer().setBackgroundColor_(GOLD.CGColor())
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

            if self._scroll is not None:
                self._scroll.setHidden_(True)
            if self._quick is not None:
                self._quick.setHidden_(True)
            self._panel.contentView().addSubview_(card)
            self._card = card
        AppHelper.callAfter(do)

    @objc.python_method
    def _clear_card(self):
        if getattr(self, "_card", None) is not None:
            self._card.removeFromSuperview()
            self._card = None
        if getattr(self, "_scroll", None) is not None:
            self._scroll.setHidden_(False)
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

    # ---- reply stopwatch + typing-dot animation -------------------------------------
    @objc.python_method
    def _sw_start(self):
        if not self.is_visible():
            return
        from Foundation import NSTimer
        self._sw_stop()
        self._sw_t0 = time.monotonic()
        self._dots = 0
        self._sw_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.35, self, "swTick:", None, True)

    def swTick_(self, timer):
        if self._sw_t0 is None or not self.is_visible():
            self._sw_stop(); return
        el = time.monotonic() - self._sw_t0
        src = self._next_src
        icon = "☁︎ Claude" if src == "claude" else "⚡ On-device"
        if getattr(self, "_status", None) is not None:
            self._status.setStringValue_("%s · %.1fs" % (icon, el))
        self._dots += 1
        if self._chat and self._chat[-1].get("pending"):   # animate the typing dots
            self._render_chat()

    @objc.python_method
    def _sw_stop(self):
        if self._sw_timer is not None:
            self._sw_timer.invalidate(); self._sw_timer = None
        self._sw_t0 = None
        if getattr(self, "_status", None) is not None:
            s = self._status.stringValue()
            if "On-device" in s or "Claude" in s:
                self._status.setStringValue_("")

    # ---- history browser ------------------------------------------------------------
    @objc.python_method
    def set_history_source(self, list_provider, on_open, on_toggle_star):
        """Wire the history providers once (at panel creation) so BOTH the in-panel clock button and the
        menu-bar item can open the browser. list_provider(query)->[session dicts]; on_open(id) loads one;
        on_toggle_star(id) stars it."""
        self._hist_provider = list_provider
        self._hist_open = on_open
        self._hist_star = on_toggle_star

    @objc.python_method
    def show_history(self, list_provider=None, on_open=None, on_toggle_star=None):
        """Open the panel showing a searchable list of past conversations (menu-bar entry point)."""
        if list_provider is not None:
            self.set_history_source(list_provider, on_open, on_toggle_star)

        def do():
            if self._panel is None:
                self._build()
            self._live = False
            self._seed_chat()
            NSApp.activateIgnoringOtherApps_(True)
            self._panel.makeKeyAndOrderFront_(None)
            self._panel.orderFrontRegardless()
            self._install_click_monitor()
            self._open_history()
        AppHelper.callAfter(do)

    def historyPressed_(self, sender):
        """The in-panel clock button — toggle the history browser using the wired providers."""
        if self._hist is not None:
            self._close_history()
            return
        if self._hist_provider is None:
            self.set_status("History unavailable")
            return
        self._open_history()

    @objc.python_method
    def _open_history(self):
        self._close_history()
        self._clear_card()
        cw = W - 2 * PAD
        top = H - PAD - INPUT_H - 20
        bottom = PAD + 6
        ch = top - bottom
        ov = NSView.alloc().initWithFrame_(NSMakeRect(PAD, bottom, cw, ch))
        ov.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        sf = NSSearchField.alloc().initWithFrame_(NSMakeRect(0, ch - 34, cw, 30))
        sf.setFont_(NSFont.systemFontOfSize_(14))
        sf.setPlaceholderString_("Search conversations…")
        sf.setFocusRingType_(NSFocusRingTypeNone)
        sf.setDelegate_(self)
        sf.setAutoresizingMask_(NSViewWidthSizable | NSViewMinYMargin)
        ov.addSubview_(sf)
        self._hist_search = sf

        sc = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch - 42))
        sc.setHasVerticalScroller_(True); sc.setAutohidesScrollers_(True); sc.setDrawsBackground_(False)
        sc.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        doc = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch - 42))
        doc.setAutoresizingMask_(NSViewWidthSizable)
        sc.setDocumentView_(doc)
        ov.addSubview_(sc)
        self._hist_doc = doc
        self._hist_scroll = sc

        if self._scroll is not None:
            self._scroll.setHidden_(True)
        if self._quick is not None:
            self._quick.setHidden_(True)
        self._panel.contentView().addSubview_(ov)
        self._hist = ov
        self.set_status("History · Esc to go back")
        self._render_history("")
        self._panel.makeFirstResponder_(sf)

    @objc.python_method
    def _render_history(self, query):
        doc = self._hist_doc
        if doc is None:
            return
        for v in list(doc.subviews()):
            v.removeFromSuperview()
        cw = doc.frame().size.width
        rows = []
        try:
            rows = self._hist_provider(query) if self._hist_provider else []
        except Exception:
            rows = []
        ROW_H = 50
        y = 4
        if not rows:
            lb = self._meta_label("No conversations." if not query else "No matches.",
                                  NSColor.secondaryLabelColor(), 8, y, cw - 16, NSTextAlignmentLeft)
            lb.setFont_(NSFont.systemFontOfSize_(13))
            doc.addSubview_(lb)
            y += 24
        for r in rows:
            doc.addSubview_(self._history_row(r, cw, y, ROW_H))
            y += ROW_H
        vis = self._hist_scroll.contentSize().height
        doc.setFrameSize_(NSMakeSize(cw, max(y + 4, vis)))
        doc.scrollRectToVisible_(NSMakeRect(0, 0, 1, 1))

    @objc.python_method
    def _history_row(self, r, cw, y, h):
        row = NSView.alloc().initWithFrame_(NSMakeRect(0, y, cw, h - 6))
        row.setWantsLayer_(True)
        row.layer().setCornerRadius_(10.0)
        row.layer().setBackgroundColor_(_rgba(1, 1, 1, 0.05).CGColor())

        star = NSButton.alloc().initWithFrame_(NSMakeRect(6, (h - 6 - 28) / 2, 30, 28))
        star.setBordered_(False); star.setTitle_("★" if r["starred"] else "☆")
        star.setFont_(NSFont.systemFontOfSize_(17))
        star.setContentTintColor_(GOLD if r["starred"] else NSColor.tertiaryLabelColor())
        star.setTag_(int(r["id"])); star.setTarget_(self); star.setAction_("histStar:")
        star.setToolTip_("Keep beyond a week" if not r["starred"] else "Starred — kept")
        row.addSubview_(star)

        opn = NSButton.alloc().initWithFrame_(NSMakeRect(38, 0, cw - 44, h - 6))
        opn.setBordered_(False); opn.setImagePosition_(0)
        title = NSMutableAttributedString.alloc().init()
        head = f"{r['label']}   ·   {r['n']} turn{'s' if r['n'] != 1 else ''}\n"
        title.appendAttributedString_(self._attr(head, NSColor.labelColor(), 13.5, 0.3))
        title.appendAttributedString_(self._attr(r["title"] or "—", NSColor.secondaryLabelColor(), 11.5))
        opn.setAttributedTitle_(title)
        opn.setAlignment_(NSTextAlignmentLeft)
        opn.cell().setLineBreakMode_(NSLineBreakByWordWrapping)
        opn.cell().setWraps_(True)
        opn.setTag_(int(r["id"])); opn.setTarget_(self); opn.setAction_("histOpen:")
        row.addSubview_(opn)
        return row

    @objc.python_method
    def _attr(self, text, color, size, weight=None):
        font = NSFont.systemFontOfSize_(size) if weight is None else NSFont.systemFontOfSize_weight_(size, weight)
        return NSAttributedString.alloc().initWithString_attributes_(
            text, {NSFontAttributeName: font, NSForegroundColorAttributeName: color})

    @objc.python_method
    def _close_history(self):
        if getattr(self, "_hist", None) is not None:
            self._hist.removeFromSuperview()
            self._hist = None
            self._hist_doc = None
            self._hist_search = None
            if self._scroll is not None:
                self._scroll.setHidden_(False)
            if self._quick is not None:
                self._quick.setHidden_(False)
            self.set_status("")

    def histOpen_(self, sender):
        sid = sender.tag()
        self._close_history()
        if self._hist_open:
            turns = self._hist_open(sid) or []
            self._chat = list(turns)
            self._viewing = True
            self._render_chat()
            self.set_status("Viewing a past conversation · Esc for live")
            self._panel.makeFirstResponder_(self._field)

    def histStar_(self, sender):
        sid = sender.tag()
        if self._hist_star:
            self._hist_star(sid)
        q = self._hist_search.stringValue() if self._hist_search is not None else ""
        self._render_history(q)

    def controlTextDidChange_(self, notif):
        if self._hist_search is not None and notif.object() is self._hist_search:
            self._render_history(self._hist_search.stringValue())

    # ---- submit ---------------------------------------------------------------------
    @objc.python_method
    def _submit(self, text: str):
        self.push_user(text)
        threading.Thread(target=lambda: self._on_submit(text, self._append), daemon=True).start()

    def quickTap_(self, sender):
        cmd = sender.toolTip()
        if cmd:
            self._submit(cmd)

    def micPressed_(self, sender):
        if self._on_mic is not None:
            self._on_mic()

    def control_textView_doCommandBySelector_(self, control, textView, selector):
        if selector == "insertNewline:":
            text = self._field.stringValue().strip()
            if text:
                self._field.setStringValue_("")
                self._submit(text)
            return True
        if selector == "cancelOperation:":
            if self._hist is not None:              # Esc in history -> back to the chat
                self._close_history()
                return True
            if self._viewing:                       # Esc while viewing old history -> back to live
                self._viewing = False
                self._chat = []
                self._seed_chat()
                self._render_chat()
                self.set_status("")
                return True
            self.hide()
            return True
        return False
