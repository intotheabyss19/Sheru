"""Sheru runtime: menubar app (rumps) or plain loop. Wires Listener -> Transcriber -> Router -> Speaker/ClaudeSession."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time

import re

from rapidfuzz import fuzz

from .audio import Listener
from .claude_code import ClaudeSession
from .journal import Journal
from .memory import Memory
from . import compose
from .actions import messaging
from .llm_local import LocalLLM
from .router import Router
from .stt import Transcriber
from .tts import Speaker

log = logging.getLogger("sheru")


class Sheru:
    def __init__(self, use_llm: bool = True) -> None:
        self.speaker = Speaker()
        self.claude = ClaudeSession()
        from . import config
        self.llm = LocalLLM(config.LOCAL_LLM) if use_llm else None
        self.fast = LocalLLM(config.LOCAL_LLM_FAST) if (use_llm and config.LOCAL_LLM_FAST) else None
        self.memory = Memory()
        self.journal = Journal()
        self.router = Router(llm=self.llm, fast=self.fast, memory=self.memory, say_async=self.speaker.speak)
        self.stt = Transcriber()
        self.listener: Listener | None = None
        self.status = "starting"
        self.followup_until = 0.0
        self.claude_cooldown_until = 0.0
        self._last_claude_ts = 0.0   # when Claude last answered; a recent one -> resume the same session (continued conversation keeps context)
        self.pending = None          # a drafted action awaiting confirm/rephrase/cancel
        self._pending_path = config.DATA_DIR / "pending.json"   # persist it so a draft survives a restart
        self._restore_pending()
        self.panel = None            # 'Type to Sheru' input panel (created when the menu-bar UI starts)
        self.dry_send = False        # tests set True to avoid sending real messages     # skip Claude Code until this time after a hard failure

    # ---- one command end-to-end -------------------------------------------------
    CONFIRM = {"send", "send it", "yes", "yeah", "yep", "confirm", "go ahead", "do it", "sure", "okay send", "ok send"}
    DENY = {"no", "nope", "cancel", "never mind", "nevermind", "don't", "dont", "forget it", "stop", "scrap it"}

    def handle_text(self, text: str, sink=None) -> str:
        """Handle one request. `sink` routes the reply: speaker.speak (voice) or a text callback (typed panel)."""
        sink = sink or self.speaker.speak
        log.info("heard: %s", text)
        from . import alarms
        low0 = re.sub(r"[.!?]+$", "", text.strip().lower())
        if alarms.is_ringing() and (low0 in {"stop", "dismiss", "dismiss it", "ok", "okay", "stop it", "silence",
                                             "enough", "turn it off", "shut up", "quiet", "snooze", "cancel"}
                                    or low0.startswith(("stop", "dismiss", "turn it off", "snooze", "shut up"))):
            alarms.stop_ring()
            sink("Alarm off.")
            return "alarm-off"
        if self.pending is not None:
            return self._handle_pending(text, sink)
        import re as _re
        if getattr(self, "_last_play", None) and _re.match(
                r"^(?:no[,.]?\s+)?(?:that'?s? not|wrong song|not (?:that|this|the right|it)|different song|try (?:again|another))\b",
                text.strip().lower()):
            q = self._last_play; self._last_play = None
            sink("Let me try again…")
            self._resolve_and_play(q, sink)
            return "retry-song"
        if self.claude.busy and text.strip().lower() in {"stop", "cancel", "never mind", "sheru stop"}:
            self.claude.cancel()
            sink("Cancelled.")
            return "Cancelled."
        res = self.router.route(text)
        self.journal.record(utterance=text, tier=res.tier, tool=getattr(res, "tool", None),
                            args=getattr(res, "args", None), speech=res.speech,
                            handoff=res.handoff, ts=time.time())
        if res.tier == 1 and self.panel is not None:
            self.panel.set_status("⚡ Sheru (local)")
        if getattr(res, "played", None):
            self._last_play = res.played
        if getattr(res, "resolve_song", None):
            if res.speech:
                sink(res.speech)
            self._record_turn(text, res.speech or f"Playing {res.resolve_song}.")
            self._resolve_and_play(res.resolve_song, sink)
            return res.speech
        if getattr(res, "draft", None):
            return self._start_draft(res.draft, sink)
        if res.handoff:
            if res.speech:
                sink(res.speech)
            self._delegate(res.handoff, sink, user_text=text)   # records the turn + resumes/injects conversation context
            return res.speech
        if res.speech:
            sink(res.speech)
        if res.followup and self._is_voice_sink(sink):
            self.allow_followup()
        self._record_turn(text, res.speech)
        return res.speech

    def _is_voice_sink(self, sink) -> bool:
        """True when the reply is spoken (push-to-talk or wake-word), not typed into the panel."""
        return sink is self.speaker.speak or sink is self._say_both

    def _record_turn(self, user: str, assistant: str | None) -> None:
        """Append this exchange to the shared conversation history (ALL tiers, not just the local LLM), capped, so
        follow-ups like 'who sings this?' or 'what about tomorrow?' have the context they need to not feel dumb."""
        h = self.router.history
        h.append({"role": "user", "content": user})
        if assistant:
            h.append({"role": "assistant", "content": assistant})
        if len(h) > 12:
            del h[: len(h) - 12]

    def _with_context(self, task: str) -> str:
        """Prepend the last few turns so a FRESH Claude thread can resolve references ('it', 'that', 'there')."""
        prior = self.router.history[-6:]
        if not prior:
            return task
        lines = [f"{'User' if m['role'] == 'user' else 'You (Sheru)'}: {m['content']}" for m in prior]
        return ("Context — earlier in this spoken conversation:\n" + "\n".join(lines)
                + f"\n\nThe user now says: {task}\n"
                "Answer only this latest request; use the above only to resolve what they are referring to.")

    # ---- draft -> confirm/rephrase -> send ------------------------------------
    def _resolve_and_play(self, query: str, sink) -> None:
        """Delegate song resolution to Claude (handles lyrics/partial titles), then play it in Spotify."""
        import re
        from . import net
        from .actions import music
        if not net.online():
            sink("I need the internet to look that song up. Set up Spotify keys for offline search.")
            return
        prompt = (f"The user wants to play a song on Spotify. The query may be a lyric, partial, or misheard: "
                  f"\"{query}\". Identify the exact track and reply with ONLY one line in this format:\n"
                  f"TITLE — ARTIST | spotify:track:TRACKID\n"
                  f"Find the track id from its open.spotify.com/track/<id> URL. If you truly can't find it, reply NOT_FOUND.")
        saved_sid = self.claude.session_id           # a one-off song lookup must not hijack the conversation thread
        self._start_progress("☁️ Claude")
        def done(final: str):
            self.claude.session_id = saved_sid
            self._stop_progress()
            m = re.search(r"spotify:track:([A-Za-z0-9]{22})", final or "")
            if m:
                label = re.split(r"\s*\|", final.strip())[0].strip() or query
                sink(music._play_uri("spotify:track:" + m.group(1), label))
            else:
                self.speaker.speak(f"I couldn't find {query} on Spotify.")
            self._after_claude()
        def failed(e):
            self.claude.session_id = saved_sid
            self._stop_progress()
            self.speaker.speak("I couldn't look that up.")
        self.claude.run(prompt, on_sentence=lambda s: None, on_done=done, on_error=failed)

    def _restore_pending(self) -> None:
        """Reload a drafted-but-unsent message from disk (survives restarts). Expire stale drafts (>1h)."""
        try:
            if self._pending_path.exists():
                p = json.loads(self._pending_path.read_text())
                if time.time() - p.get("ts", 0) <= 3600:
                    self.pending = p
                else:
                    self._pending_path.unlink(missing_ok=True)
        except Exception:
            self.pending = None

    def _save_pending(self) -> None:
        """Persist the pending draft (minus the sink callback, which isn't serializable)."""
        try:
            if self.pending is None:
                self._pending_path.unlink(missing_ok=True)
            else:
                self._pending_path.write_text(json.dumps({k: v for k, v in self.pending.items() if k != "sink"}))
        except Exception:
            pass

    def _start_draft(self, d: dict, sink) -> str:
        recipient = d["recipient"]
        contact = messaging.resolve_contact(recipient)
        if contact is None:                      # unknown -> ask for the number once, then continue
            self.pending = {"kind": "need_number", "recipient": recipient, "gist": d.get("gist", ""),
                            "app": d.get("app") or "whatsapp", "ts": time.time(), "sink": sink}
            self._save_pending()
            msg = f"I don't have {recipient}'s number saved. What's their WhatsApp number (with country code)?"
            sink(msg)
            return msg
        draft = compose.draft(self.llm, recipient, d.get("gist", ""))
        self.pending = {"kind": "message", "recipient": recipient, "contact": contact,
                        "draft": draft, "gist": d.get("gist", ""), "app": d.get("app") or "whatsapp",
                        "ts": time.time(), "sink": sink}
        self._save_pending()
        who = contact["name"] if contact else recipient
        self._present_draft(who, draft, sink)
        return draft

    def _handle_pending(self, text: str, sink) -> str:
        p = self.pending
        if p.get("kind") == "need_number":
            return self._handle_number(text, sink)
        low = text.strip().lower().rstrip(".!")
        if low in self.CONFIRM or low.startswith(("send", "yes", "go ahead", "do it")):
            return self._send_pending(sink)
        if low in self.DENY or low.startswith(("no", "cancel", "don't", "dont", "forget", "scrap")):
            self.pending = None
            self._save_pending()
            sink("Okay, I won't send it.")
            return "cancelled"
        # otherwise: treat as a rephrase instruction
        p["draft"] = compose.draft(self.llm, p["recipient"], p["gist"], revision=text, previous=p["draft"])
        p["ts"] = time.time()
        self._save_pending()
        who = (p.get("contact") or {}).get("name") or p["recipient"]
        self._present_draft(who, p["draft"], sink)
        return p["draft"]

    def _handle_number(self, text: str, sink) -> str:
        """Awaiting a phone number for an unknown recipient: save it to Sheru's book, then draft."""
        p = self.pending
        low = text.strip().lower()
        if low in self.DENY or low.startswith(("no", "cancel", "forget", "never", "don't", "dont")):
            self.pending = None
            self._save_pending()
            sink("Okay, cancelled.")
            return "cancelled"
        m = re.search(r"\+?\d[\d\s\-]{6,}\d", text)     # a phone number with country code
        if not m:
            sink(f"I need {p['recipient']}'s number with country code (like +91…). What is it?")
            return "need-number"
        from .actions import contacts_book
        contacts_book.add(p["recipient"].title(), m.group(0))
        d = {"recipient": p["recipient"], "gist": p["gist"], "app": p["app"]}
        self.pending = None
        return self._start_draft(d, sink)             # resolves now that the number is saved

    def _send_pending(self, sink) -> str:
        p = self.pending
        self.pending = None
        self._save_pending()
        c = p["contact"]
        if not c:
            sink(f"I couldn't find {p['recipient']} in your contacts, so I can't send it.")
            return "no-contact"
        if p["app"] == "whatsapp":
            ok = messaging.send_whatsapp(c["handle"], p["draft"], dry_run=self.dry_send)
        elif c["kind"] == "phone":
            ok = messaging.send_imessage(c["handle"], p["draft"], dry_run=self.dry_send)
        else:
            ok = False
        if ok:
            sink(f"Sent to {c['name']}{' on WhatsApp' if p['app']=='whatsapp' else ''}.")
            result = "sent"
        else:
            messaging.prefill(c["handle"], p["draft"], app=p["app"], dry_run=self.dry_send)
            sink(f"I've opened it in {'WhatsApp' if p['app']=='whatsapp' else 'Messages'} ready to send — just press return.")
            result = "prefilled"
        self.journal.record(utterance=f"[send message to {c['name']}]", tier=1, tool="send_message",
                            args={"handle": c["handle"], "text": p["draft"], "via": result},
                            speech=result, handoff=None, ts=time.time())
        return result

    def activate(self) -> None:
        """Push-to-talk trigger (F5 or mic button): show the panel and listen for one command."""
        if getattr(self, "_listening", False):
            return                       # already capturing — ignore the re-press
        log.info("ACTIVATED — listening for a command")
        self._ensure_mic_level()
        self.show_type_panel()
        if self.panel is not None:
            self.panel._set_out("Listening…")
            self.panel.set_status("🎙 listening…")
        threading.Thread(target=self._listen_and_handle, name="sheru-ptt", daemon=True).start()

    def _listen_and_handle(self) -> None:
        from .audio import capture_once
        if not getattr(self, "_warm", False):
            self._say_both("One moment, still starting up.")
            return
        self._listening = True
        try:
            first = True
            while True:                                    # keep listening while a follow-up is expected
                if self.panel is not None:
                    self.panel.set_status("🎙 listening…")
                    if first:
                        self.panel._set_out("Listening…")
                audio = capture_once(max_wait=8.0)
                if audio is None:
                    if first and self.panel is not None:
                        self.panel._set_out("(didn't catch anything — speak a bit louder/closer)")
                    log.info("ptt: no speech captured")
                    break
                text = self.stt.transcribe(audio)
                log.info("ptt stt %.2fs: %r", self.stt.last_latency, text)
                from . import recorder
                recorder.save(audio, text, self.stt.last_latency, kind="voice")
                cmd = self.strip_wake(text)                # strip an optional wake word if still said
                cmd = cmd if cmd else text
                if cmd:
                    if self.panel is not None:
                        self.panel.push_user(cmd)          # show what Sheru HEARD in the chat (so you catch STT errors)
                    self.handle_text(cmd, sink=self._say_both)
                # if a Claude handoff is in flight, wait it out so the answer + follow-up window arrive first
                t_end = time.monotonic() + 155
                while self.claude.busy and time.monotonic() < t_end:
                    time.sleep(0.1)
                self.speaker.wait()                        # let Sheru finish talking before the mic re-opens
                # re-listen only when a follow-up is expected: a draft awaiting confirm, or Sheru just answered
                if self.pending is None and time.monotonic() >= self.followup_until:
                    break
                first = False
        finally:
            self._listening = False

    def _start_progress(self, label: str) -> None:
        """Show a live '<label> · Ns' stopwatch in the panel (e.g. '☁️ Claude · 8s')."""
        import time as _t
        from Foundation import NSTimer
        from PyObjCTools import AppHelper
        self._progress_label = label
        self._progress_t0 = _t.monotonic()
        def _mk(_):
            self._progress_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.0, _ProgressTarget.alloc().initWithApp_(self), "tick:", None, True)
            self._progress_tick()
        AppHelper.callAfter(_mk)

    def _progress_tick(self) -> None:
        import time as _t
        if self.panel is not None and getattr(self, "_progress_t0", None):
            self.panel.set_status(f"{self._progress_label} · {int(_t.monotonic() - self._progress_t0)}s")

    def _stop_progress(self) -> None:
        t = getattr(self, "_progress_timer", None)
        if t is not None:
            t.invalidate(); self._progress_timer = None
        self._progress_t0 = None
        if self.panel is not None:
            self.panel.set_status("")

    def _say_both(self, text: str) -> None:
        """Normal mode: speak AND show in the panel."""
        self.speaker.speak(text)
        if self.panel is not None:
            self.panel._append(text)

    def show_onboarding(self) -> None:
        if getattr(self, "_onboarding", None) is None:
            from .onboarding import Onboarding
            self._onboarding = Onboarding.alloc().initWithApp_(self)
        self._onboarding.show()

    def show_type_panel(self) -> None:
        """Show the 'Type to Sheru' box (silent text input). Requires the NSApplication run loop."""
        if self.panel is None:
            from .panel import TypePanel
            self.panel = TypePanel.alloc().initWithSubmit_onMic_(
                lambda text, sink: self.handle_text(text, sink=sink),
                lambda: self.activate())
            self.panel.set_history_provider(self.recent_interactions)
        self.panel.show()

    def recent_interactions(self, n: int = 6) -> list:
        """Recent (utterance, reply) pairs for the panel's Spotlight-style recent list (newest first)."""
        pairs, pend = [], None
        for m in self.router.history:
            if m["role"] == "user":
                pend = m["content"]
            elif m["role"] == "assistant" and pend is not None:
                pairs.append((pend, m["content"])); pend = None
        if pend is not None:
            pairs.append((pend, ""))
        return list(reversed(pairs))[:n]

    def show_alarms(self) -> None:
        """Speak the active alarms/timers (menu-bar '⏰ Alarms' click)."""
        from . import alarms
        act = alarms.active()
        if not act:
            self.speaker.speak("You have no alarms or timers set.")
            return
        parts = [f"{a['label'].lower()} in {alarms.human_remaining(a['remaining'])}" for a in act[:5]]
        self.speaker.speak(f"You have {len(act)} set: " + "; ".join(parts) + ".")

    def _present_draft(self, who: str, draft: str, sink) -> None:
        """Show a message draft as a Siri-style card in the panel (typed mode), else speak/append the prompt."""
        if (self.panel is not None and not self._is_voice_sink(sink)
                and getattr(self.panel, "is_visible", None) and self.panel.is_visible()):
            self.panel.show_message_card(
                who, draft,
                on_send=lambda: self._panel_pending("send it"),
                on_cancel=lambda: self._panel_pending("cancel"))
        else:
            sink(f"Here's the message to {who}: “{draft}”. Want me to send it, or change anything?")

    def _panel_pending(self, word: str) -> None:
        """Run a confirm/cancel word through the pending state machine off the UI thread (send can block)."""
        threading.Thread(target=lambda: self.handle_text(word, sink=self.panel._append), daemon=True).start()

    def allow_followup(self, seconds: float = 6.0) -> None:
        self.followup_until = time.monotonic() + seconds

    def _delegate(self, task: str, sink=None, user_text: str | None = None) -> None:
        """Prefer Claude Code (subscription); fall back to the local model offline or on failure.
        Resume the same Claude session for a follow-up (a Claude turn <2 min ago) so continued conversation
        keeps its context; otherwise start a fresh thread but inject the recent turns for reference-resolution."""
        from . import net
        sink = sink or self.speaker.speak
        resume = (self.claude.session_id is not None
                  and time.monotonic() - self._last_claude_ts < 120)
        if time.monotonic() >= self.claude_cooldown_until and net.online():
            self.status = "claude"
            self._start_progress("☁️ Claude")
            payload = task if resume else self._with_context(task)    # reads PRIOR turns
            if user_text is not None:
                self._record_turn(user_text, None)                   # then record this turn (assistant filled on done)

            def _done(final: str):
                self._stop_progress()
                if final:
                    self.router.history.append({"role": "assistant", "content": final[:800]})
                self._last_claude_ts = time.monotonic()
                self._after_claude()

            self.claude.run(payload, on_sentence=sink, resume=resume, on_done=_done,
                            on_error=lambda e: (self._stop_progress(), self._local_fallback(task, e, sink)))
        else:
            if user_text is not None:
                self._record_turn(user_text, None)
            self._start_progress("⚡ Sheru (offline)")
            self._local_fallback(task, None, sink)
            self._stop_progress()

    def _local_fallback(self, task: str, err: str | None, sink=None) -> None:
        sink = sink or self.speaker.speak
        if err:
            log.warning("claude -p failed (%s); local fallback, cooldown 5 min", err[:120])
            self.claude_cooldown_until = time.monotonic() + 300     # retry Claude after 5 min
        if self.llm is not None:
            ctx = self.memory.context_block(task) if self.memory else ""
            ans = self.llm.answer(task, self.router.history[-6:], extra_system=ctx)
            sink(ans)
            self.router.history.append({"role": "assistant", "content": ans})
        else:
            sink("I can't reach Claude right now and I have no local model to fall back on.")
        self._last_claude_ts = time.monotonic()
        self._after_claude()

    def _after_claude(self) -> None:
        self.status = "listening"
        self.allow_followup(12)     # a spoken answer invites a follow-up; keep the mic open a bit longer

    # ---- wake-word detection on the transcript -----------------------------------
    WAKE_RE = re.compile(r"^\W*(?:hey|hi|ok|okay|yo)?\W*(sheru|sharu|shiru|shero|sheroo|cheru|shiro|sherry|sheroux)\b[\s,.!?]*", re.I)

    def strip_wake(self, text: str) -> str | None:
        """Return the command after the wake word, '' if only the wake word, None if no wake word."""
        m = self.WAKE_RE.match(text)
        if m:
            return text[m.end():].strip()
        first = re.sub(r"[^a-z ]", "", text.lower()).split()[:2]
        if first and fuzz.ratio(" ".join(first), "hey sheru") >= 80:
            return " ".join(text.split()[2:]).strip()
        return None

    # ---- background voice loop --------------------------------------------------
    def warm(self) -> None:
        t0 = time.perf_counter()
        if self.llm:
            self.llm.load()
        self.stt.transcribe(__import__("numpy").zeros(16000, dtype="float32"))  # loads parakeet
        log.info("models warm in %.1fs (tts voice: %s)", time.perf_counter() - t0, self.speaker.voice_name)
        self._warm = True
        try:
            from . import reminders
            n = reminders.restore(self.speaker.speak)
            if n:
                log.info("restored %d pending reminder(s)", n)
        except Exception as e:
            log.error("reminder restore failed: %s", e)

    def start_trigger_socket(self) -> None:
        """Listen on a Unix socket so ANY external key/script (Karabiner, Raycast, kanata-style) can activate
        Sheru by running `sheru trigger`. Decouples activation from any one hotkey mechanism."""
        import socket, threading
        from . import config
        from PyObjCTools import AppHelper
        path = str(config.DATA_DIR / "sheru.sock")
        try:
            import os
            os.path.exists(path) and os.unlink(path)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path); srv.listen(4)
        def _loop():
            while True:
                try:
                    conn, _ = srv.accept()
                    conn.close()
                    AppHelper.callAfter(self.activate)
                except OSError:
                    break
        threading.Thread(target=_loop, name="sheru-trigger", daemon=True).start()
        log.info("trigger socket ready: run `sheru trigger` to activate (bind any key to it)")

    def start_voice(self) -> None:
        self._mic_selftest()
        self.listener = Listener(is_busy=lambda: self.speaker.speaking).start()
        threading.Thread(target=self._voice_loop, name="sheru-main", daemon=True).start()
        self.status = "listening"

    def _ensure_mic_level(self) -> None:
        import subprocess
        try:
            cur = int(subprocess.run(["osascript", "-e", "input volume of (get volume settings)"],
                                     capture_output=True, text=True).stdout.strip() or 50)
            if cur < 85:
                subprocess.run(["osascript", "-e", "set volume input volume 90"])
                log.info("raised mic input volume %d -> 90", cur)
        except Exception:
            pass

    def _mic_selftest(self) -> None:
        """Capture 1s and log RMS — RMS≈0 means this process has no real mic access (TCC denied / silent)."""
        try:
            import sounddevice as sd, numpy as np
            dev = sd.query_devices(kind="input")
            x = sd.rec(16000, samplerate=16000, channels=1, dtype="float32"); sd.wait()
            rms = float(np.sqrt((x ** 2).mean()))
            log.info("MIC SELF-TEST: device=%r rms=%.5f %s", dev["name"], rms,
                     "(OK, audio flowing)" if rms > 0.001 else "(SILENT — grant Microphone to 'Sheru' in System Settings)")
        except Exception as e:
            log.error("MIC SELF-TEST failed: %s", e)

    def _voice_loop(self) -> None:
        for audio in self.listener.segments():
            text = self.stt.transcribe(audio)
            log.info("stt %.2fs (%.1fs audio): %r", self.stt.last_latency, len(audio) / 16000, text)
            if not text:
                continue
            cmd = self.strip_wake(text)
            if cmd is None:
                if time.monotonic() < self.followup_until:
                    cmd = text                      # follow-up without the wake word
                else:
                    continue                        # not talking to Sheru
            if not cmd:
                self.speaker.speak("Yes?")
                self.allow_followup()
                continue
            self.handle_text(cmd)


class _OnceTarget:
    pass


def _install_progress_target():
    import objc
    from Foundation import NSObject
    class ProgressTarget(NSObject):
        def initWithApp_(self, app):
            self = objc.super(ProgressTarget, self).init()
            self._app = app
            return self
        def tick_(self, timer):
            self._app._progress_tick()
    globals()["_ProgressTarget"] = ProgressTarget


def _wait_warm(app, timeout=60):
    import time as _t
    t0 = _t.monotonic()
    while not getattr(app, "_warm", False) and _t.monotonic() - t0 < timeout:
        _t.sleep(0.2)


def run_menubar(app: Sheru) -> None:
    import rumps
    import objc
    from Foundation import NSObject

    _install_progress_target()

    class OnceTarget(NSObject):
        def initWithFn_(self, fn):
            self = objc.super(OnceTarget, self).init()
            self._fn = fn
            return self
        def fire_(self, timer):
            self._fn(timer)
    globals()["_OnceTarget"] = OnceTarget

    class SheruApp(rumps.App):
        def __init__(self):
            import rumps
            from . import config, alarms
            icon = str(config.ROOT / "assets" / "menubar.png")
            super().__init__("Sheru", icon=icon, template=True, quit_button=None)
            self._alarm_item = rumps.MenuItem("⏰ Alarms: none", callback=lambda _: app.show_alarms())
            self._stop_item = rumps.MenuItem("🔔 Stop ringing", callback=lambda _: alarms.stop_ring())
            self.menu = ["🎙 Talk to Sheru", "Type to Sheru", "Setup / Permissions…", "🎵 Set up Spotify…",
                         "Mute", None, self._alarm_item, self._stop_item, None, "Quit Sheru"]

        @rumps.timer(2)
        def _tick(self, _):
            self._refresh_alarms()

        def _refresh_alarms(self):
            # render the soonest alarm as the menu-bar title + item (the old code set title=None, erasing it)
            try:
                from . import alarms
                act = alarms.active()
                ringing = alarms.is_ringing()
                self.title = "🔔" if ringing else ("⏰" if act else None)
                if ringing:
                    self._alarm_item.title = "🔔 Alarm ringing — press Stop below"
                elif act:
                    n = act[0]
                    extra = f"  +{len(act) - 1} more" if len(act) > 1 else ""
                    self._alarm_item.title = f"⏰ {n['label']} in {alarms.human_remaining(n['remaining'])}{extra}"
                else:
                    self._alarm_item.title = "⏰ Alarms: none"
            except Exception:
                pass

        @rumps.clicked("🎙 Talk to Sheru")
        def _talk(self, _):
            app.activate()

        @rumps.clicked("Type to Sheru")
        def _type(self, _):
            app.show_type_panel()

        @rumps.clicked("Setup / Permissions…")
        def _setup(self, _):
            app.show_onboarding()

        @rumps.clicked("🎵 Set up Spotify…")
        def _spotify(self, _):
            import subprocess
            from . import config
            from .actions import music
            subprocess.run(["open", "https://developer.spotify.com/dashboard"], check=False)
            w1 = rumps.Window("Log in, click 'Create app' (any name; redirect URI http://localhost),\n"
                              "then open the app's Settings and paste its Client ID here:",
                              "Set up Spotify — 1 of 2", ok="Next", cancel="Cancel", dimensions=(360, 22))
            r1 = w1.run()
            if not r1.clicked or not r1.text.strip():
                return
            r2 = rumps.Window("Now paste the Client Secret:", "Set up Spotify — 2 of 2",
                              ok="Save", cancel="Cancel", dimensions=(360, 22)).run()
            if not r2.clicked or not r2.text.strip():
                return
            cid, sec = r1.text.strip(), r2.text.strip()
            config.update_profile("spotify_client_id", cid)
            config.update_profile("spotify_client_secret", sec)
            ok = music._token(cid, sec) is not None
            rumps.notification("Sheru", "Spotify",
                               "Connected — I can play songs directly now." if ok
                               else "Those keys didn't work. Re-run Set up Spotify and re-paste them.")

        @rumps.clicked("Mute")
        def _mute(self, sender):
            sender.state = not sender.state
            (app.listener.muted.set if sender.state else app.listener.muted.clear)()
            sender.title = "Unmute" if sender.state else "Mute"

        @rumps.clicked("Quit Sheru")
        def _quit(self, _):
            rumps.quit_application()

    import os
    from .wizard import is_done
    sheru_app = SheruApp()                    # creates the NSApplication first
    from . import alarms as _alarms
    from PyObjCTools import AppHelper as _AH
    _alarms.set_on_change(lambda: _AH.callAfter(sheru_app._refresh_alarms))   # refresh the menu bar when alarms change
    threading.Thread(target=app.warm, daemon=True).start()
    app.start_trigger_socket()
    if os.environ.get("SHERU_ALWAYS_ON"):
        threading.Thread(target=lambda: (_wait_warm(app), app.start_voice()), daemon=True).start()
    else:
        import sheru.hotkey as _hk
        ok = _hk.register(app.activate, key_code=_hk.KEY_F18)   # F5 (remapped->F18) via NSEvent, needs Accessibility
        log.info("F18/F5 hotkey via NSEvent: %s | also: `sheru trigger` (bind any key)", ok)
    if not is_done():
        from Foundation import NSTimer
        # show onboarding shortly after the run loop starts
        def _first_run(timer): app.show_onboarding()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.8, _OnceTarget.alloc().initWithFn_(_first_run), "fire:", None, False)
    sheru_app.run()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sheru")
    p.add_argument("command", nargs="?", help="'setup' (first-run wizard) or 'trigger' (activate a running Sheru)")
    p.add_argument("--text", help="run one command from text (no mic) and exit")
    p.add_argument("--listen", action="store_true", help="voice loop in the terminal, no menubar")
    p.add_argument("--no-llm", action="store_true", help="skip the local LLM (Tier 0 + Claude only)")
    p.add_argument("-v", "--verbose", action="store_true")
    a = p.parse_args(argv)
    if a.command == "setup":
        from .wizard import run as run_wizard
        run_wizard()
        return 0
    if a.command == "import-contacts":
        from .google_contacts import import_all
        return import_all()
    if a.command == "import-vcf":
        from .contacts_vcf import import_vcf
        return import_vcf(a.text)
    if a.command == "trigger":
        import socket
        from . import config
        try:
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.connect(str(config.DATA_DIR / "sheru.sock")); c.close()
            return 0
        except OSError:
            print("Sheru isn't running."); return 1
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(name)s %(message)s", force=True)
    for noisy in ("httpx", "httpcore", "urllib3", "filelock", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    app = Sheru(use_llm=not a.no_llm)
    if a.text:
        print(app.handle_text(a.text))
        while app.claude.busy or app.speaker.speaking:
            time.sleep(0.2)
        return 0
    from .wizard import is_done
    if not is_done():
        print("\n  First time? Run  \033[1muv run sheru setup\033[0m  to grant permissions and see what I can do.\n")
    if a.listen:
        app.warm(); app.start_voice()
        print("Sheru listening — say 'hey sheru'. Ctrl-C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    run_menubar(app)
    return 0
