"""Sheru Settings — a real preferences window (glassy, native), so the menu bar can stay minimal.

Absorbs the old menu toggles (voice, mic, orb, reply language) and adds: talkback loudness + speed, a sound-cue
theme with a Test button, a custom orb image, an editable personality/preferences (data/preferences.md), a
one-click "open a trainer session", and Quit (to free the resident models / unified memory).

Everything writes through config setters (persisted to data/profile.json) and takes effect immediately — no
restart. Built on the same NSPanel + NSVisualEffectView pattern as onboarding.py.
"""
from __future__ import annotations

import threading

import objc
from AppKit import (
    NSPanel, NSTextField, NSButton, NSColor, NSFont, NSApp, NSVisualEffectView, NSPopUpButton, NSSlider,
    NSTextView, NSScrollView, NSOpenPanel, NSBox,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView,
    NSBackingStoreBuffered, NSButtonTypeMomentaryPushIn, NSLineBreakByWordWrapping, NSBezelStyleRounded,
)
from Foundation import NSObject, NSMakeRect
from PyObjCTools import AppHelper

from . import config

W = 560
LANGS = [("auto", "Match what I speak"), ("en", "English"), ("hi", "Hindi / Hinglish")]
ORBS = [("orb", "Orb (lightest)"), ("particles", "Particles"), ("rings", "Rings"), ("bars", "Bars")]
CUE_LABELS = [("chime", "Chime (bright)"), ("chime_high", "Chime (very high)"),
              ("soft", "Soft"), ("classic", "Classic")]


def _label(text, x, y, w, h, size=13, bold=False, dim=False):
    f = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    f.setStringValue_(text)
    f.setBezeled_(False); f.setDrawsBackground_(False); f.setEditable_(False); f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size))
    f.setTextColor_(NSColor.secondaryLabelColor() if dim else NSColor.labelColor())
    f.setLineBreakMode_(NSLineBreakByWordWrapping)
    return f


class Settings(NSObject):
    def initWithApp_(self, app):
        self = objc.super(Settings, self).init()
        if self is None:
            return None
        self._app = app
        self._win = None
        return self

    # ---- helpers ---------------------------------------------------------------------------------------------
    @objc.python_method
    def _popup(self, items, selected_key, action, x, y, w=300):
        pb = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(x, y, w, 26), False)
        pb.addItemsWithTitles_([lbl for _k, lbl in items])
        for i, (k, _lbl) in enumerate(items):
            if k == selected_key:
                pb.selectItemAtIndex_(i)
        pb.setTarget_(self); pb.setAction_(action)
        self._view.addSubview_(pb)
        return pb

    @objc.python_method
    def _button(self, title, action, x, y, w=140, h=28):
        b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        b.setTitle_(title); b.setBezelStyle_(NSBezelStyleRounded); b.setButtonType_(NSButtonTypeMomentaryPushIn)
        b.setTarget_(self); b.setAction_(action)
        self._view.addSubview_(b)
        return b

    @objc.python_method
    def _slider(self, minv, maxv, val, action, x, y, w=220):
        s = NSSlider.alloc().initWithFrame_(NSMakeRect(x, y, w, 24))
        s.setMinValue_(minv); s.setMaxValue_(maxv); s.setDoubleValue_(val)
        s.setContinuous_(False); s.setTarget_(self); s.setAction_(action)
        self._view.addSubview_(s)
        return s

    @objc.python_method
    def _header(self, text, y):
        self._view.addSubview_(_label(text, 26, y, W - 52, 16, size=11, bold=True, dim=True))

    @objc.python_method
    def _sep(self, y):
        box = NSBox.alloc().initWithFrame_(NSMakeRect(26, y, W - 52, 1))
        box.setBoxType_(2)  # NSBoxSeparator
        self._view.addSubview_(box)

    # ---- build -----------------------------------------------------------------------------------------------
    @objc.python_method
    def _build(self):
        HGT = 780
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskFullSizeContentView
        win = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, HGT), style, NSBackingStoreBuffered, False)
        win.setTitle_("Sheru Settings")
        win.setReleasedWhenClosed_(False)
        vev = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, W, HGT))
        vev.setAutoresizingMask_(18)
        win.contentView().addSubview_(vev)
        self._view = vev

        y = HGT - 52
        self._view.addSubview_(_label("Sheru Settings", 26, y, W - 52, 30, size=22, bold=True))
        y -= 34

        # VOICE
        self._header("VOICE", y); y -= 24
        voice_items = list(config.KOKORO_VOICES) + [("__sarvam__", "Sarvam (cloud, Hindi)")]
        sel = "__sarvam__" if config.TTS_BACKEND == "sarvam" else config.KOKORO_VOICE
        self._voice = self._popup(voice_items, sel, "voiceChanged:", 26, y, 300)
        self._button("Test", "testVoice:", 336, y, 90, 26)
        y -= 36
        self._view.addSubview_(_label("Loudness", 26, y + 2, 80, 20, size=12, dim=True))
        self._gain = self._slider(0.08, 0.32, config.TTS_GAIN, "gainChanged:", 110, y, 180)
        self._view.addSubview_(_label("Speed", 310, y + 2, 60, 20, size=12, dim=True))
        self._speed = self._slider(0.8, 1.3, config.KOKORO_SPEED, "speedChanged:", 366, y, 160)
        y -= 30
        self._sep(y); y -= 22

        # MICROPHONE
        self._header("MICROPHONE", y); y -= 24
        from .audio import list_input_devices, preferred_device
        mic_items = [("__auto__", "Auto (built-in — best isolation)")] + [(str(i), n) for i, n in list_input_devices()]
        cur_mic = "__auto__" if config.MIC_DEVICE in (None, "") else str(config.MIC_DEVICE)
        self._mic = self._popup(mic_items, cur_mic, "micChanged:", 26, y, 400)
        y -= 32
        self._sep(y); y -= 22

        # APPEARANCE
        self._header("APPEARANCE", y); y -= 24
        self._view.addSubview_(_label("Listening animation", 26, y + 2, 150, 20, size=12, dim=True))
        self._orb = self._popup(ORBS, config.ORB_STYLE, "orbChanged:", 180, y, 180)
        self._button("Custom image…", "chooseOrb:", 372, y, 150, 26)
        y -= 32
        self._sep(y); y -= 22

        # SOUND CUES
        self._header("SOUND CUES", y); y -= 24
        self._view.addSubview_(_label("Tone theme", 26, y + 2, 100, 20, size=12, dim=True))
        self._cue = self._popup(CUE_LABELS, config.CUE_STYLE, "cueChanged:", 130, y, 200)
        self._button("Play", "testCues:", 342, y, 90, 26)
        y -= 32
        self._sep(y); y -= 22

        # REPLY LANGUAGE
        self._header("REPLY LANGUAGE", y); y -= 24
        self._lang = self._popup(LANGS, config.REPLY_LANG, "langChanged:", 26, y, 260)
        y -= 32
        self._sep(y); y -= 22

        # PERSONALITY & PREFERENCES
        self._header("PERSONALITY & PREFERENCES  —  Sheru reads this live", y); y -= 20
        sv = NSScrollView.alloc().initWithFrame_(NSMakeRect(26, y - 128, W - 52, 128))
        sv.setHasVerticalScroller_(True); sv.setBorderType_(1)
        tv = NSTextView.alloc().initWithFrame_(sv.contentView().bounds())
        tv.setEditable_(True); tv.setRichText_(False); tv.setFont_(NSFont.systemFontOfSize_(12))
        try:
            tv.setString_(config.PREFERENCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            tv.setString_("")
        sv.setDocumentView_(tv)
        self._view.addSubview_(sv); self._prefs = tv
        y -= 128                       # to the bottom of the text editor
        y -= 40                        # gap + button height so Save sits clearly BELOW the editor
        self._button("Save preferences", "savePrefs:", 26, y, 160, 28)
        y -= 20
        self._sep(y); y -= 20

        # ACTIONS
        self._button("Open a trainer session", "openTrainer:", 26, y, 200, 30)
        self._button("Quit Sheru (free memory)", "quitSheru:", 250, y, 200, 30)
        y -= 40
        self._button("Done", "done:", W - 120, 20, 94, 32)

        self._win = win

    # ---- actions ---------------------------------------------------------------------------------------------
    def voiceChanged_(self, sender):
        i = sender.indexOfSelectedItem()
        items = list(config.KOKORO_VOICES) + [("__sarvam__", "")]
        key = items[i][0] if 0 <= i < len(items) else config.KOKORO_VOICE
        if key == "__sarvam__":
            config.set_tts("sarvam")
        else:
            config.set_kokoro_voice(key)
            self._speak_sample()

    def testVoice_(self, sender):
        self._speak_sample()

    def gainChanged_(self, sender):
        config.set_tts_gain(sender.doubleValue()); self._speak_sample()

    def speedChanged_(self, sender):
        config.set_kokoro_speed(sender.doubleValue()); self._speak_sample()

    def micChanged_(self, sender):
        i = sender.indexOfSelectedItem()
        from .audio import list_input_devices
        items = [("__auto__", "")] + [(str(idx), n) for idx, n in list_input_devices()]
        key = items[i][0] if 0 <= i < len(items) else "__auto__"
        config.set_mic(None if key == "__auto__" else int(key))

    def orbChanged_(self, sender):
        key = ORBS[sender.indexOfSelectedItem()][0]
        config.set_orb_style(key)
        try:
            self._app._ensure_orb()
        except Exception:
            pass

    def chooseOrb_(self, sender):
        p = NSOpenPanel.openPanel()
        p.setAllowsMultipleSelection_(False)
        p.setAllowedFileTypes_(["png", "gif", "jpg", "jpeg", "heic", "svg"])
        if p.runModal() == 1 and p.URLs():
            config.update_profile("orb_image", p.URLs()[0].path())

    def cueChanged_(self, sender):
        key = CUE_LABELS[sender.indexOfSelectedItem()][0]
        config.set_cue_style(key)
        from . import cues
        self._app._cue_paths = cues.ensure_cues()   # regenerate + refresh the app's cached paths

    def testCues_(self, sender):
        import subprocess
        from . import cues
        p = getattr(self._app, "_cue_paths", None) or cues.ensure_cues()
        try:
            subprocess.Popen(["afplay", "-v", "0.9", p["listen"]])
        except Exception:
            pass

    def langChanged_(self, sender):
        config.set_reply_lang(LANGS[sender.indexOfSelectedItem()][0])

    def savePrefs_(self, sender):
        try:
            config.PREFERENCES_FILE.parent.mkdir(parents=True, exist_ok=True)
            config.PREFERENCES_FILE.write_text(self._prefs.string(), encoding="utf-8")
            sender.setTitle_("Saved ✓")
        except Exception:
            sender.setTitle_("Save failed")

    def openTrainer_(self, sender):
        def _go():
            try:
                from .actions import trainer
                trainer.open_trainer("")
            except Exception:
                pass
        threading.Thread(target=_go, daemon=True).start()

    def quitSheru_(self, sender):
        NSApp.terminate_(None)

    def done_(self, sender):
        self._win.orderOut_(None)

    # ---- lifecycle -------------------------------------------------------------------------------------------
    @objc.python_method
    def _speak_sample(self):
        try:
            self._app.speaker.speak("This is how I sound.")
        except Exception:
            pass

    @objc.python_method
    def show(self):
        if self._win is None:
            self._build()
        NSApp.activateIgnoringOtherApps_(True)
        self._win.center()
        self._win.makeKeyAndOrderFront_(None)
