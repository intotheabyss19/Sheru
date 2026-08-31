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
        self._search_busy = False    # True while a local web-search+summarize thread runs — gates the mic like Claude
        self.claude_cooldown_until = 0.0
        self._last_claude_ts = 0.0   # when Claude last answered; a recent one -> resume the same session (continued conversation keeps context)
        self.pending = None          # a drafted action awaiting confirm/rephrase/cancel
        self._pending_path = config.DATA_DIR / "pending.json"   # persist it so a draft survives a restart
        self._restore_pending()
        self.panel = None            # 'Type to Sheru' input panel (created when the menu-bar UI starts)
        self.orb = None              # Siri-style listening orb/particles, shown while capturing (lazy)
        self._orb_timer = None       # NSTimer driving the orb from the live mic level
        self._orb_style = None       # which style the current orb was built with
        self.dry_send = False        # tests set True to avoid sending real messages     # skip Claude Code until this time after a hard failure
        self._typing_mode = False    # True while in hands-free TYPING mode: spoken words get typed into the active field
        self._ended_convo = False    # set True for one turn by an explicit sign-off ("no"/"that's all") -> voice loop stops
        self._send_key = (36, [])    # per-session TYPING send key: (keycode, modifiers). Default Return; "send button is shift+enter" changes it

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
        if self._typing_mode:                              # hands-free TYPING: type what was said, or exit the mode
            low = re.sub(r"[.!?]+$", "", text.strip().lower())
            if re.search(r"\b(disable|deactivate|stop|exit|turn off|end|quit|close)\s+(?:the\s+)?(?:typing|dictation|type|hands\s?free)\s*mode\b", low) \
                    or low in ("stop typing", "disable typing", "typing off", "exit typing", "done typing"):
                self._typing_mode = False
                sink("Typing mode off.")
                if self._is_voice_sink(sink):
                    self.allow_followup(12)                # stay listening for the next normal command
                return "typing-off"
            _sk = re.match(r"^(?:set\s+)?(?:the\s+)?send\s+(?:button|key)\s+(?:is|to|as)\s+(.+)$"
                           r"|^(?:use|send\s+with)\s+(.+?)(?:\s+to\s+send)?$", low)   # change the session's send key
            if _sk:
                spec = next((g for g in _sk.groups() if g), "")
                parsed = self._parse_send_key(spec)
                if parsed:
                    self._send_key = parsed
                    label = ("+".join(m.title() for m in parsed[1]) + "+Enter") if parsed[1] else "Enter"
                    sink(f"Okay, I'll send with {label} in this typing session.")
                    if self._is_voice_sink(sink):
                        self.allow_followup(20)
                    return "send-key-set"
            self._type_and_send(text)
            if self._is_voice_sink(sink):
                self.allow_followup(20)                    # keep the mic open for the NEXT line to dictate
            return "typed"
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
        if self.claude.busy and re.match(r"^(?:sheru\s+)?(?:stop|cancel|never ?mind|shut up|quiet|enough|that'?s enough)"
                                         r"(?:\s+(?:it|that|now|please))?[.! ]*$", text.strip().lower()):
            self.claude.cancel()
            sink("Cancelled.")
            return "Cancelled."
        res = self.router.route(text)
        if self.panel is not None:
            self.panel.set_source("local")     # default ⚡ local; _start_progress flips it to ☁️ claude on escalation
        if getattr(res, "feedback", None):
            self.journal.label_last(res.feedback, note="explicit-rating")   # rate the PREVIOUS action before logging this turn
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
        if getattr(res, "call", None):
            return self._start_call(res.call, sink)
        if getattr(res, "typing", None):
            return self._start_typing(res.typing, sink)
        if getattr(res, "search", None):
            if res.speech:
                sink(res.speech)                 # "Let me check." ack
            self._search_local(res.search, sink, user_text=text)
            return res.speech
        if res.handoff:
            if res.speech:
                sink(res.speech)
            self._delegate(res.handoff, sink, user_text=text,   # records the turn + resumes/injects conversation context
                           artifact=getattr(res, "artifact", None))
            return res.speech
        if (res.tool and res.tool not in ("feedback_good", "feedback_bad", "stop", "help", "status",
                                          "remember", "set_reply_lang", "set_voice")
                and self._is_voice_sink(sink) and res.speech and not res.handoff):
            self._act_n = getattr(self, "_act_n", 0) + 1     # occasionally ask for a rating (good/bad -> journal)
            if self._act_n % 4 == 0:
                res.speech = res.speech + " How did I do?"
                res.followup = True
        if res.speech:
            sink(res.speech)
        if getattr(res, "open_panel", False):          # input impractical by voice (a link) -> reveal the chat to type
            try:
                from PyObjCTools import AppHelper
                AppHelper.callAfter(self.show_type_panel)
            except Exception:
                pass
        # Keep the mic open after EVERY command so you can chain ("open X" → "no, open Y" → "now search Z")
        # without re-pressing F5 — the conversation stays alive until you end it ("no"/"that's all"/"goodbye")
        # or two quiet windows. Only a sign-off (end_convo) closes it. The strict follow-up VAD + the speaker-done
        # gate below keep Sheru's own voice from re-triggering. (This replaces the old FIRE_AND_FORGET exclusion,
        # which forced an F5 press after every open/search/play — the #1 "continued conversation doesn't work".)
        tool = getattr(res, "tool", None)
        if tool == "end_convo":                    # an explicit sign-off -> the voice loop stops after this turn
            self._ended_convo = True
        asks_back = bool(res.speech) and res.speech.rstrip().endswith("?")   # a question needs time for a reply
        keep_open = bool(res.speech) and tool != "end_convo"
        if self._is_voice_sink(sink) and (res.followup or asks_back or keep_open):
            self.allow_followup(25 if (res.followup or asks_back) else 20)   # keep listening >=20s (Yash's ask)
            log.info("mic RE-ARMED after tool=%s (continued conversation)", tool)
        self._record_turn(text, res.speech)
        return res.speech

    def _is_voice_sink(self, sink) -> bool:
        """True when the reply is spoken (push-to-talk or wake-word), not typed into the panel.
        Compare the underlying FUNCTION, not the bound method: `sink is self._say_both` is ALWAYS False because
        each `self._say_both` access creates a new bound-method object. That silently disabled EVERY follow-up arm
        gated on this — the real, long-standing 'continued conversation doesn't work' bug."""
        f = getattr(sink, "__func__", None)
        return f is self._say_both.__func__ or f is self.speaker.speak.__func__

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
        from .actions import contacts_book
        address = contacts_book.address_for(recipient)     # e.g. saved 'Crocodile' -> greet as 'Madam'
        draft = compose.draft(self.llm, address, d.get("gist", ""))
        self.pending = {"kind": "message", "recipient": recipient, "contact": contact,
                        "draft": draft, "gist": d.get("gist", ""), "app": d.get("app") or "whatsapp",
                        "ts": time.time(), "sink": sink}
        self._save_pending()
        who = address if address.lower() != recipient.strip().lower() else (contact["name"] if contact else recipient)
        self._present_draft(who, draft, sink)
        return draft

    def _start_call(self, d: dict, sink) -> str:
        """Set up a WhatsApp call and ask to confirm — NEVER auto-dials. Confirm in chat -> _place_call."""
        recipient = d["recipient"]
        video = bool(d.get("video"))
        contact = messaging.resolve_contact(recipient)
        if contact is None:
            self.pending = {"kind": "call_need_number", "recipient": recipient, "video": video,
                            "app": "whatsapp", "ts": time.time(), "sink": sink}
            self._save_pending()
            msg = f"I don't have {recipient}'s number saved. What's their WhatsApp number (with country code)?"
            sink(msg)
            return msg
        who = contact.get("name") or recipient
        self.pending = {"kind": "call", "recipient": recipient, "contact": contact, "video": video,
                        "app": "whatsapp", "ts": time.time(), "sink": sink}
        self._save_pending()
        verb = "video-call" if video else "call"
        msg = f"Ready to {verb} {who} on WhatsApp. Say 'yes' to place the call, or 'cancel'."
        self._present_call(who, video, sink)
        return msg

    def _present_call(self, who: str, video: bool, sink) -> None:
        """Show a Call/Cancel card in the panel (typed mode), else ask by voice/text. Never dials on its own."""
        if (self.panel is not None and not self._is_voice_sink(sink)
                and getattr(self.panel, "is_visible", None) and self.panel.is_visible()):
            self.panel.show_call_card(who, video,
                                      on_call=lambda: self._panel_pending("yes"),
                                      on_cancel=lambda: self._panel_pending("cancel"))
        else:
            sink(f"Ready to {'video-call' if video else 'call'} {who} on WhatsApp. Say 'yes' to call, or 'cancel'.")

    def _place_call(self, sink) -> str:
        p = self.pending
        self.pending = None
        self._save_pending()
        c = p.get("contact")
        if not c or not c.get("handle"):
            sink(f"I couldn't find {p['recipient']}'s number, so I can't place the call.")
            return "no-contact"
        who = c.get("name") or p["recipient"]
        sink(f"{'Video-calling' if p.get('video') else 'Calling'} {who} on WhatsApp…")
        ok = messaging.call_whatsapp(c["handle"], video=p.get("video", False), dry_run=self.dry_send)
        if not ok:
            sink("I opened the chat but couldn't start the call — tap the call button in WhatsApp to connect.")
            return "call-failed"
        return "calling"

    def _start_typing(self, t: dict, sink) -> str:
        """Enter hands-free TYPING mode: from now on spoken words get typed into the focused field.
        If a recipient is named, open their WhatsApp chat first so the input is focused. Needs Accessibility."""
        import subprocess
        from . import permissions
        if not permissions.accessibility_trusted():        # without it keystroke synthesis silently hangs macOS
            sink("I need Accessibility access to type for you. I'm opening Settings — switch Sheru on under "
                 "Accessibility, then ask me again.")
            permissions.request_accessibility()
            return "need-accessibility"
        self._send_key = (36, [])                          # each typing session starts sending with Enter
        recipient = t.get("recipient")
        if recipient:
            contact = messaging.resolve_contact(recipient)
            if contact and contact.get("handle"):
                digits = re.sub(r"\D", "", contact["handle"])
                subprocess.run(["open", f"whatsapp://send?phone={digits}"], check=False)
                who = contact.get("name") or recipient
                time.sleep(1.6)                       # let the chat load and focus the message field
                self._typing_mode = True
                msg = f"Typing mode on for {who}. Say what you want to send. Say 'disable typing mode' to stop."
            else:
                self._typing_mode = True              # no chat to open, but honour the mode into whatever's focused
                msg = (f"I don't have {recipient}'s chat saved, so open it yourself. "
                       "Typing mode is on — say 'disable typing mode' to stop.")
        else:
            self._typing_mode = True
            msg = "Typing mode on. I'll type what you say into the active window. Say 'disable typing mode' to stop."
        sink(msg)
        voice = self._is_voice_sink(sink)
        if voice:
            self.allow_followup(20)                        # re-open the mic so the first dictated line is captured
        log.info("typing mode ON (recipient=%s, voice_sink=%s, follow-up armed=%s)", recipient, voice, voice)
        return msg

    def _type_and_send(self, text: str) -> None:
        """Type spoken text into the frontmost app's focused field, then Return to send IF it's a chat app.
        In a document, Return would just be a newline, so we only auto-send in messaging apps. Needs Accessibility."""
        import subprocess
        if self.dry_send:                             # tests: don't actually emit synthetic keystrokes
            logging.info("typing-mode (dry): %r", text)
            return
        safe = text.replace("\\", "\\\\").replace('"', '\\"')
        try:                                              # timeouts so a revoked grant can't freeze the app
            subprocess.run(["osascript", "-e", f'tell application "System Events" to keystroke "{safe}"'],
                           capture_output=True, timeout=8)
            front = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to name of first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=4).stdout.strip().lower()
        except subprocess.TimeoutExpired:
            log.warning("typing keystroke timed out — Accessibility may be revoked; exiting typing mode")
            self._typing_mode = False
            self._say_both("I lost typing access. Turn Sheru back on under Accessibility in Settings.")
            return
        except Exception:
            front = ""
        if front in ("whatsapp", "messages", "telegram", "discord", "slack", "signal"):
            keycode, mods = getattr(self, "_send_key", (36, []))   # session send key (default Return; e.g. Shift-Enter)
            modstr = (" using {" + ", ".join(f"{m} down" for m in mods) + "}") if mods else ""
            subprocess.run(["osascript", "-e", f'tell application "System Events" to key code {keycode}{modstr}'],
                           capture_output=True, timeout=4)

    @staticmethod
    def _parse_send_key(spec: str):
        """'shift enter' / 'command+return' -> (keycode, [modifiers]); None if unrecognized."""
        s = spec.lower().replace("+", " ")
        mods = []
        if "shift" in s: mods.append("shift")
        if "command" in s or "cmd" in s: mods.append("command")
        if "control" in s or "ctrl" in s: mods.append("control")
        if "option" in s or "alt" in s: mods.append("option")
        if "enter" in s or "return" in s:
            return (36, mods)
        if "tab" in s:
            return (48, mods)
        return None

    def _handle_pending(self, text: str, sink) -> str:
        p = self.pending
        if p.get("kind") == "artifact":
            return self._handle_artifact_pending(text, sink)
        if p.get("kind") == "need_number":
            return self._handle_number(text, sink)
        low = text.strip().lower().rstrip(".!")
        if p.get("kind") == "call_need_number":
            if low in self.DENY or low.startswith(("no", "cancel", "forget", "never", "don't", "dont")):
                self.pending = None; self._save_pending(); sink("Okay, no call."); return "cancelled"
            mnum = re.search(r"\+?\d[\d\s\-]{6,}\d", text)
            if not mnum:
                sink(f"I need {p['recipient']}'s number with country code (like +91…). What is it?")
                return "need-number"
            from .actions import contacts_book
            contacts_book.add(p["recipient"].title(), mnum.group(0))
            d = {"recipient": p["recipient"], "video": p.get("video", False), "app": "whatsapp"}
            self.pending = None
            return self._start_call(d, sink)
        if p.get("kind") == "call":
            if low in self.CONFIRM or low.startswith(("yes", "call", "ring", "go ahead", "do it", "yeah", "yep", "sure")):
                return self._place_call(sink)
            if low in self.DENY or low.startswith(("no", "cancel", "don't", "dont", "forget", "scrap", "stop")):
                self.pending = None; self._save_pending(); sink("Okay, no call."); return "cancelled"
            sink("Say 'yes' to place the call, or 'cancel'.")
            return "await-call"
        if low in self.CONFIRM or low.startswith(("send", "yes", "go ahead", "do it")):
            return self._send_pending(sink)
        if low in self.DENY or low.startswith(("no", "cancel", "don't", "dont", "forget", "scrap")):
            self.pending = None
            self._save_pending()
            sink("Okay, I won't send it.")
            return "cancelled"
        # NEW-INTENT escape: if this is clearly a DIFFERENT command (not a rewording of the message), drop the
        # draft and run it — instead of folding "actually, play some music" into the message body. Also clears a
        # stale draft restored after a restart so it can't hijack the first real command.
        if re.match(r"^(?:play|open|launch|quit|close|stop|pause|skip|next|previous|resume|mute|unmute|volume|"
                    r"set (?:the )?volume|turn (?:it |the )?(?:up|down|on|off)|what(?:'?s| is| time)|who is|"
                    r"search|google|look up|call|ring|remind me|set (?:a|an|the) (?:timer|alarm)|brightness|dim|"
                    r"maximi[sz]e|run shortcut|do not disturb|focus)\b", low):
            self.pending = None
            self._save_pending()
            return self.handle_text(text, sink)     # route it fresh now that the draft is dropped (pending is None)
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
        t = getattr(self, "_ptt_thread", None)
        if getattr(self, "_listening", False) and t is not None and t.is_alive():
            return                       # genuinely still capturing — ignore the re-press
        self._listening = False          # clear a stale flag from a thread that already died (fixes "shows listening but won't")
        log.info("ACTIVATED — listening for a command")
        self._ensure_mic_level()
        self._ensure_panel()             # create it HIDDEN so the voice sink can render in; click the orb to reveal
        try:
            self._ensure_orb()
            self.orb.show()              # the Siri-style orb IS the listening indicator now
            self.orb.set_state("local")  # each session starts in the local (orange) colour
            self._start_orb_driver()
        except Exception as e:
            log.error("orb failed (%s) — showing the panel instead", e)
            self.show_type_panel()
            if self.panel is not None:
                self.panel._set_out("Listening…" if getattr(self, "_warm", False) else "⏳ Warming up…")
        self._ptt_thread = threading.Thread(target=self._listen_and_handle, name="sheru-ptt", daemon=True)
        self._ptt_thread.start()

    def _listen_and_handle(self) -> None:
        from .audio import capture_once, ListenerConfig, preferred_device
        # follow-up captures (after a reply) use a MUCH higher VAD threshold + a little more trailing silence, so a
        # continued conversation needs deliberate speech and background noise / room chatter doesn't keep it going.
        fu_cfg = ListenerConfig(vad_threshold=0.6, min_speech_s=0.4, end_silence_s=0.55, device=preferred_device())
        if not getattr(self, "_warm", False):
            if self.panel is not None:
                self.panel._set_out("⏳ Warming up models… one moment.")
                self.panel.set_status("⏳ warming up…")
            t_warm = time.monotonic() + 15
            while not getattr(self, "_warm", False) and time.monotonic() < t_warm:
                time.sleep(0.2)
            if not getattr(self, "_warm", False):
                self._say_both("Still starting up — give me a few seconds and try again.")
                if self.panel is not None:
                    self.panel.set_status("")
                return
        self._listening = True
        try:
            first = True
            while True:                                    # keep listening while a follow-up is expected
                if self.panel is not None:
                    self.panel.set_status("🎙 listening…" if first else "🎙 your turn — I'm listening")
                    if first:
                        self.panel._set_out("Listening…")
                # first listen: 8s. follow-up: the armed window (>=6s) to START speaking, from AFTER Sheru spoke.
                wait = 8.0 if first else max(getattr(self, "_followup_window", 6.0), 6.0)
                if not first:
                    log.info("ptt: follow-up window open %.0fs — say your next thing", wait)
                self._listen_cue()                    # a soft 'your turn' tone (EVERY open, first + follow-up) so you
                self._cued_speak = False              # know exactly when to speak; re-arm the 'about to speak' cue
                audio = capture_once(max_wait=wait, cfg=(None if first else fu_cfg))   # stricter on follow-ups
                self._followup_armed = False              # consume; handle_text re-arms if this reply invites one
                self._ended_convo = False                 # handle_text sets this True only on an explicit sign-off
                # Transcribe up front. A window with no USABLE speech — the mic timed out (audio None) OR the STT
                # returned '' (a silence/noise hallucination dropped by the confidence gate) — is a "quiet window":
                # it must NOT arm a follow-up, or the loop spins forever on room noise (the AGC amplifies hiss).
                text = self.stt.transcribe(audio) if audio is not None else ""
                if audio is not None:
                    log.info("ptt stt %.2fs: %r", self.stt.last_latency, text)
                if not text.strip():
                    if first:
                        if self.panel is not None:
                            self.panel._set_out("(didn't catch anything — speak a bit louder/closer)")
                        log.info("ptt: no speech captured")
                        break
                    if self._typing_mode:                  # in typing mode a quiet window means "done dictating"
                        self._typing_mode = False
                        log.info("ptt: quiet in typing mode — exiting typing mode")
                        self._say_both("Typing mode off.")
                        break
                    # a follow-up window went quiet — CHECK IN once before closing, so the conversation never
                    # drops on you silently (Yash's ask). Only end after 'Anything else?' also gets no reply.
                    if not getattr(self, "_asked_done", False):
                        self._asked_done = True
                        self._say_both("Anything else?")
                        _t0 = time.monotonic()
                        while self.speaker.speaking and time.monotonic() - _t0 < 8:
                            time.sleep(0.1)
                        self._followup_window = 20.0      # >=20s to answer (Yash's ask)
                        continue                          # re-open the mic for the answer
                    log.info("ptt: quiet after 'Anything else?' — ending the conversation")
                    break
                self._asked_done = False                  # a real reply -> reset the 'checked in' state
                from . import recorder
                recorder.save(audio, text, self.stt.last_latency, kind="voice")
                cmd = self.strip_wake(text)                # strip an optional wake word if still said
                cmd = cmd if cmd else text
                if cmd:
                    if self.panel is not None:
                        self.panel.push_user(cmd)          # show what Sheru HEARD in the chat (so you catch STT errors)
                    try:
                        self.handle_text(cmd, sink=self._say_both)
                    except Exception as e:                 # a handler blowing up must NOT silently kill the loop
                        log.exception("handle_text failed for %r", cmd)
                        self._say_both("Sorry, something went wrong with that one.")
                # GATE: don't re-open the mic until Sheru is COMPLETELY done — Claude finished AND every streamed
                # sentence has finished playing — else it records its own voice, which starts a new turn that cuts
                # the reply off. claude.busy stays True through a 'speak -> search -> speak more' answer, so this
                # also keeps the mic shut during the mid-reply pause.
                if self.panel is not None:
                    self.panel.set_status("🔊 speaking…")
                t_end = time.monotonic() + 175
                log.info("ptt gate: waiting for speaker/claude/search to finish (busy=%s speaking=%s search=%s)",
                         self.claude.busy, self.speaker.speaking, self._search_busy)
                while (self.claude.busy or self.speaker.speaking or self._search_busy) and time.monotonic() < t_end:
                    time.sleep(0.1)
                time.sleep(0.6)                            # let a just-arrived FINAL sentence begin playing…
                while (self.claude.busy or self.speaker.speaking or self._search_busy) and time.monotonic() < t_end:
                    time.sleep(0.1)                        # …then wait that out too
                time.sleep(0.35)                           # echo guard: let the audio tail clear the mic buffer
                if time.monotonic() >= t_end:
                    log.warning("ptt gate: hit the 175s cap — speaker/claude/search never cleared")
                # re-listen only when a follow-up is expected: a draft awaiting confirm, or a reply that armed one.
                # Uses the flag (armed by THIS turn's reply), so the window is measured from now — AFTER speaking —
                # not decayed by however long the reply took to say.
                _armed = getattr(self, "_followup_armed", False)
                _ended = getattr(self, "_ended_convo", False)
                log.info("ptt gate done: pending=%s armed=%s typing=%s ended=%s",
                         self.pending is not None, _armed, self._typing_mode, _ended)
                if _ended:                                    # an explicit sign-off ("no"/"that's all") -> stop now
                    self._ended_convo = False
                    break
                # Otherwise ALWAYS keep listening — the ONLY ways to end are a sign-off (above) or two quiet
                # windows (silence -> "Anything else?" -> silence). Never close abruptly after a command (Yash's ask).
                if self.pending is None and not _armed:
                    self._followup_window = 20.0              # a command that didn't arm one (e.g. cancel) still gets a 20s window
                first = False
        finally:
            self._listening = False
            from . import avcapture
            avcapture.release_shared()                       # free the mic (indicator off) — the conversation is over
            self._stop_orb_driver()                         # hide the orb + stop its timer when listening ends
            if self.panel is not None:                      # never leave a stale "listening…" showing
                self.panel.set_status("")

    def _start_progress(self, label: str) -> None:
        """Show a live '<label> · Ns' stopwatch in the panel (e.g. '☁️ Claude · 8s')."""
        import time as _t
        from Foundation import NSTimer
        from PyObjCTools import AppHelper
        self._progress_label = label
        self._progress_t0 = _t.monotonic()
        state = "claude" if "Claude" in label else "local"
        if self.orb is not None:                            # recolour the orb: blue = escalated to Claude.
            AppHelper.callAfter(lambda: self.orb and self.orb.set_state(state))   # MUST be main thread (CoreAnimation)
        if self.panel is not None:                          # and tag the chat turn ⚡ local / ☁️ Claude
            self.panel.set_source(state)
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
        if self.orb is not None:                            # back to local (orange) once Claude is done
            from PyObjCTools import AppHelper
            AppHelper.callAfter(lambda: self.orb and self.orb.set_state("local"))   # main thread (CoreAnimation)
        if self.panel is not None:
            self.panel.set_status("")

    def _say_both(self, text: str) -> None:
        """Normal mode: speak AND show in the panel."""
        if not getattr(self, "_cued_speak", False):   # a soft, distinct 'Sheru is about to speak' tone before the
            self._cued_speak = True                    # reply's first sentence — so you know to stop and listen
            self._speak_cue()
        self.speaker.speak(text)
        if self.panel is not None:
            self.panel._append(text)

    def show_onboarding(self) -> None:
        if getattr(self, "_onboarding", None) is None:
            from .onboarding import Onboarding
            self._onboarding = Onboarding.alloc().initWithApp_(self)
        self._onboarding.show()

    def _ensure_panel(self) -> None:
        """Create the 'Type to Sheru' panel (hidden) so the voice sink can render into it even before it's shown."""
        if self.panel is None:
            from .panel import TypePanel
            self.panel = TypePanel.alloc().initWithSubmit_onMic_(
                lambda text, sink: self.handle_text(text, sink=sink),
                lambda: self.activate())
            self.panel.set_history_provider(self.recent_interactions)
            from . import conversations as _C
            self.panel.set_history_source(lambda q: _C.list_sessions(query=q), _C.session_turns, _C.toggle_star)

    def show_type_panel(self) -> None:
        """Show the 'Type to Sheru' box (silent text input). Requires the NSApplication run loop."""
        self._ensure_panel()
        self.panel.show()

    def show_history_panel(self) -> None:
        """Show the searchable history browser — past conversations grouped by session, starrable; unstarred
        ones expire after a week (pruned at startup)."""
        from . import conversations as C
        self._ensure_panel()
        self.panel.show_history(lambda q: C.list_sessions(query=q), C.session_turns, C.toggle_star)

    def request_permissions(self) -> None:
        """Prompt for Accessibility + Automation and open the right System Settings panes — so auto-send,
        the F5 hotkey, and typing mode work under Sheru's own identity instead of you clicking Send yourself."""
        from . import permissions
        permissions.request_all()
        try:
            import rumps
            rumps.notification("Sheru — Permissions",
                               "Toggle Sheru ON in the panes that opened",
                               "Enable Sheru under Accessibility and Automation, then it can send messages, "
                               "place calls, and type for you hands-free.")
        except Exception:
            pass

    # ---- listening orb (Siri-style) ------------------------------------------------
    def _ensure_orb(self) -> None:
        """Create/rebuild the listening orb for the current style (config.ORB_STYLE: 'orb'|'particles')."""
        from . import config
        from .orb import ListeningOrb, view_for
        want = config.ORB_STYLE
        if self.orb is None or self._orb_style != want:
            if self.orb is not None:
                try:
                    self.orb.hide()
                except Exception:
                    pass
            self.orb = ListeningOrb.alloc().initWithOnClick_(self._orb_clicked)
            self.orb._view_cls = view_for(want)
            self._orb_style = want

    def _orb_clicked(self) -> None:
        """Clicking the orb reveals the chat panel."""
        try:
            self.show_type_panel()
        except Exception as e:
            log.error("orb click -> panel failed: %s", e)

    def _start_orb_driver(self) -> None:
        from Foundation import NSTimer
        from PyObjCTools import AppHelper
        if self._orb_timer is not None:
            return
        _install_orb_target()

        def _mk(_):
            self._orb_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1 / 30.0, _OrbTarget.alloc().initWithApp_(self), "tick:", None, True)
        AppHelper.callAfter(_mk)

    def _orb_tick(self) -> None:
        from . import audio
        import math
        import time as _t
        if self.orb is not None:
            # gentle idle "breathing" so the orb is ALWAYS visibly present (listening, Sheru speaking, your-turn),
            # PLUS your voice grows it on top — amplified, because the built-in mic runs quiet (peak ~0.05).
            idle = 0.10 + 0.04 * (0.5 + 0.5 * math.sin(_t.monotonic() * 2.2))
            self.orb.set_level(min(1.0, idle + audio.LEVEL["v"] * 5.0))

    def _stop_orb_driver(self) -> None:
        t = self._orb_timer
        if t is not None:
            try:
                t.invalidate()
            except Exception:
                pass
            self._orb_timer = None
        if self.orb is not None:
            self.orb.hide()

    def recent_interactions(self, n: int = 25) -> list:
        """Recent (utterance, reply) pairs for the panel's history — from the PERSISTENT journal so past
        conversations show and survive restarts, falling back to the in-memory session if the journal is empty."""
        from . import journal as _journal
        pairs = _journal.recent_pairs(n)
        if pairs:
            return pairs
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

    def _offer_artifact(self, artifact: dict, sink) -> None:
        """Claude finished writing the file — set a pending offer to run it or move it elsewhere."""
        from pathlib import Path
        path = Path(artifact.get("path", ""))
        if not path.exists():
            return                              # Claude didn't write where we asked; leave its spoken reply as-is
        self.pending = {"kind": "artifact", "path": str(path), "request": artifact.get("request", "")}
        self.allow_followup(20)                 # keep the mic open for the yes / move answer
        sink(f"Saved it to {path.name}. Want to see it, or should I move it somewhere?")

    RUN_WORDS = ("yes", "yeah", "yep", "sure", "ok", "okay", "show", "see", "play", "run", "go", "do it")

    def _handle_artifact_pending(self, text: str, sink) -> str:
        from pathlib import Path
        from .actions import generate
        p = self.pending
        path = Path(p["path"])
        low = text.strip().lower().rstrip(".!")
        m = re.search(r"\b(?:move|save|put|copy|place|relocate)\b.*?\b(?:to|in|into|inside|under)\b\s+(.+)$", low)
        if m or re.search(r"\b(?:move|relocate)\b", low):
            dest = generate.resolve_dir(m.group(1) if m else "")
            if dest is None:
                sink("Where should I move it? Say a folder like 'LearningPhase' or a full path.")
                return "artifact-need-dir"
            try:
                generate.move(path, dest)
            except Exception as e:
                self.pending = None
                sink(f"I couldn't move it: {e}")
                return "artifact-move-failed"
            self.pending = None
            sink(f"Moved it to {dest}.")
            return "artifact-moved"
        if low in self.DENY or low.startswith(("no", "cancel", "don't", "dont", "leave", "forget", "nothing")):
            self.pending = None
            sink(f"Okay, it's saved at {path} if you want it later.")
            return "artifact-kept"
        if low in self.CONFIRM or low.startswith(self.RUN_WORDS) or any(w in low for w in ("see", "run", "play", "show")):
            self.pending = None
            sink("Running it now.")

            def _go():
                ok, out = generate.run(path)
                if ok:
                    sink("Done." + (f" It printed: {out}" if out and len(out) < 160 else ""))
                else:
                    sink(f"It didn't run cleanly — {out}. Want me to have Claude fix it?")
            threading.Thread(target=_go, daemon=True).start()
            return "artifact-run"
        sink("Say 'yes' to run it, or 'move it to a folder'.")
        return "artifact-reoffer"

    def _search_local(self, query: str, sink, user_text: str | None = None) -> None:
        """LOCAL web-search + summarize (on-device model). Escalate to Claude ONLY if it can't answer — this
        keeps current-info queries off Claude, serving the local-first goal. Stays in the 'local' orb colour."""
        from .actions import search_local
        if user_text is not None:
            self._record_turn(user_text, None)
        self._search_busy = True                 # gate the mic while we fetch+summarize (else it records the answer)

        def _go():
            try:
                ans = None
                try:
                    ans = search_local.search_and_summarize(query, self.llm)
                except Exception as e:
                    log.warning("local search failed: %s", e)
                if ans:
                    log.info("answered LOCALLY via web-search + summarize")
                    sink(ans)
                    self.router.history.append({"role": "assistant", "content": ans[:800]})
                    self.allow_followup(20)
                else:
                    log.info("local search couldn't answer -> escalating to Claude")
                    self._delegate(query, sink)  # claude.busy is set synchronously -> the gate switches to it
            finally:
                self._search_busy = False
        threading.Thread(target=_go, name="sheru-search", daemon=True).start()

    def _listen_cue(self) -> None:
        """A soft, short tone signalling 'your turn — speak now' when the mic opens — so you know it's listening
        without watching the screen. Quiet + brief so it doesn't get recorded as speech."""
        try:
            import subprocess
            subprocess.Popen(["afplay", "-v", "0.3", "/System/Library/Sounds/Pop.aiff"])
        except Exception:
            pass

    def _speak_cue(self) -> None:
        """A soft, DISTINCT tone right before Sheru starts replying — 'I'm about to speak'. Different sound from the
        listen cue (Tink vs Pop) so the two are unmistakable eyes-free: Pop = your turn, Tink = my turn."""
        try:
            import subprocess
            subprocess.Popen(["afplay", "-v", "0.25", "/System/Library/Sounds/Tink.aiff"])
        except Exception:
            pass

    def allow_followup(self, seconds: float = 6.0) -> None:
        """Arm a follow-up: after Sheru finishes SPEAKING, keep the mic open ~`seconds` (min 6) for the user to
        start a reply. Armed as a flag, NOT a deadline set now — so the window can't be eaten by the time it
        takes to speak a long reply (the bug that made continued conversation 'not work')."""
        self._followup_armed = True
        self._followup_window = max(float(seconds), 6.0)
        self.followup_until = time.monotonic() + seconds     # kept for any legacy readers

    def _delegate(self, task: str, sink=None, user_text: str | None = None, artifact: dict | None = None) -> None:
        """Prefer Claude Code (subscription); fall back to the local model offline or on failure.
        Resume the same Claude session for a follow-up (a Claude turn <2 min ago) so continued conversation
        keeps its context; otherwise start a fresh thread but inject the recent turns for reference-resolution.
        When `artifact` is set, Claude was asked to WRITE a file; on completion, offer to run or move it."""
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
                if artifact:
                    self._offer_artifact(artifact, sink)

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
        self.allow_followup(20)     # a spoken answer invites a follow-up; keep the mic open a bit longer

    # ---- wake-word detection on the transcript -----------------------------------
    WAKE_RE = re.compile(r"^\W*(?:hey|hi|ok|okay|yo)?\W*(sheru|sharu|shiru|shero|sheroo|cheru|shiro|sherry|sheroux|charu|chaaru|churu|jeru|jaru|jeroo|sheroo)\b[\s,.!?]*", re.I)

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
        try:                                       # raw-mic fallback only: a hot mic (>75%) CLIPS -> Whisper gibberish.
            from . import avcapture                 # with Voice-Processing I/O active, its AGC handles level — leave gain alone.
            if not avcapture.available():
                import subprocess                   # cap it at 65% on startup (reboots reset it back up). Don't raise a low one.
                cur = int(subprocess.run(["osascript", "-e", "input volume of (get volume settings)"],
                                         capture_output=True, text=True, timeout=4).stdout.strip() or 65)
                if cur > 75:
                    subprocess.run(["osascript", "-e", "set volume input volume 65"], capture_output=True, timeout=4)
                    log.info("mic input was %d%% (clips) -> set to 65%%", cur)
        except Exception:
            pass
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
                    try:
                        conn.settimeout(0.3)
                        msg = conn.recv(16)             # 'chat' -> panel, 'ping' -> single-instance probe, else voice
                    except Exception:
                        msg = b""
                    conn.close()
                    if msg == b"ping":
                        continue                        # just checking we're alive; don't activate anything
                    if msg == b"chat":
                        AppHelper.callAfter(self.show_type_panel)
                    else:
                        AppHelper.callAfter(self.activate)
                except OSError:
                    break
        threading.Thread(target=_loop, name="sheru-trigger", daemon=True).start()
        log.info("trigger socket ready: run `sheru trigger` to activate (bind any key to it)")

    def start_voice(self) -> None:
        self._mic_selftest()
        from .audio import ListenerConfig, preferred_device
        self.listener = Listener(ListenerConfig(device=preferred_device()),
                                 is_busy=lambda: self.speaker.speaking).start()
        threading.Thread(target=self._voice_loop, name="sheru-main", daemon=True).start()
        self.status = "listening"

    def _ensure_mic_level(self) -> None:
        # Voice-Processing I/O runs its own AGC, so leave the OS input gain alone when it's active — poking the
        # hardware gain is the anti-pattern that caused the clipping/garbling in the first place.
        from . import avcapture
        if avcapture.available():
            return
        # Raw-mic fallback only: keep the mic at a NON-CLIPPING level. This used to RAISE it to 90%, which CLIPS
        # the input -> Whisper hallucinates gibberish. 65% + the STT's peak-normalization handles a quiet mic fine.
        import subprocess
        try:
            cur = int(subprocess.run(["osascript", "-e", "input volume of (get volume settings)"],
                                     capture_output=True, text=True, encoding="utf-8", errors="replace")
                      .stdout.strip() or 65)
            if not (45 <= cur <= 70):
                subprocess.run(["osascript", "-e", "set volume input volume 65"], capture_output=True, timeout=4)
                log.info("mic input %d%% -> 65%% (avoid clipping)", cur)
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
            try:
                self.handle_text(cmd)
            except Exception:                       # one bad handler must not kill the always-on listener for good
                log.exception("handle_text failed for %r", cmd)
                self.speaker.speak("Sorry, something went wrong with that one.")


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


def _install_orb_target():
    if "_OrbTarget" in globals():
        return
    import objc
    from Foundation import NSObject
    class OrbTarget(NSObject):
        def initWithApp_(self, app):
            self = objc.super(OrbTarget, self).init()
            self._app = app
            return self
        def tick_(self, timer):
            self._app._orb_tick()
    globals()["_OrbTarget"] = OrbTarget


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
            import rumps, os
            from . import config, alarms
            # Yash's preferred menu-bar mark: the waveform template PNG (black silhouette + alpha -> renders crisp,
            # auto-inverts for light/dark). Set as the ICON so it's ALWAYS visible; the title is left free for the
            # alarm badge. Earlier "missing icon" was really the _refresh_alarms bug that set title=None with no icon.
            # Menu-bar mark = a white, shape-only SF Symbol (config.MENUBAR_ICON), rendered as a TEMPLATE image on
            # the status-item button — the native Mac look (auto white-on-dark / black-on-light). Applied in the
            # first _refresh_alarms tick because the status item only exists once the run loop starts; the 🦁 title
            # here just fills the gap for that first ~2s. The button image must be set via the modern button API —
            # rumps' own icon= uses a pre-10.10 call Tahoe ignores.
            super().__init__("Sheru", title="🦁", quit_button=None)
            self._icon_symbol = config.MENUBAR_ICON
            self._cur_sym = None                   # currently-applied symbol (change-detection)
            self._alarm_item = rumps.MenuItem("No Alarms Set", callback=lambda _: app.show_alarms())
            self._stop_item = rumps.MenuItem("Stop Ringing", callback=lambda _: alarms.stop_ring())
            # Voice picker: choose a specific LOCAL (Kokoro) voice — several male options — or the Sarvam cloud voice.
            self._voice_items = {}
            voice = rumps.MenuItem("Voice")
            for vid, label in config.KOKORO_VOICES:
                it = rumps.MenuItem(label, callback=lambda s, v=vid: self._set_kokoro_voice(v))
                it.state = 1 if (config.TTS_BACKEND == "kokoro" and config.KOKORO_VOICE == vid) else 0
                voice.add(it); self._voice_items[vid] = it
            voice.add(rumps.separator)
            self._voice_sarvam = rumps.MenuItem("Sarvam (cloud, Hindi)", callback=lambda _: self._set_voice("sarvam"))
            self._voice_sarvam.state = 1 if config.TTS_BACKEND == "sarvam" else 0
            voice.add(self._voice_sarvam)
            # microphone picker — the built-in mic is auto-preferred (best noise isolation); switch here
            from .audio import list_input_devices, preferred_device
            cur = preferred_device()
            self._mic_items = {}
            mic = rumps.MenuItem("Microphone")
            auto = rumps.MenuItem("Auto (built-in)", callback=lambda _: self._set_mic(None))
            auto.state = 1 if config.MIC_DEVICE in (None, "") else 0
            mic.add(auto); self._mic_items["auto"] = auto
            for idx, name in list_input_devices():
                it = rumps.MenuItem(name, callback=lambda s, i=idx: self._set_mic(i))
                it.state = 1 if (config.MIC_DEVICE not in (None, "") and idx == cur) else 0
                mic.add(it); self._mic_items[idx] = it
            # listening animation style (orb / particles)
            self._orb_items = {}
            style = rumps.MenuItem("Listening Style")
            for key, label in (("orb", "Orb (lightest)"), ("particles", "Particles"),
                               ("rings", "Rings"), ("bars", "Bars")):
                it = rumps.MenuItem(label, callback=lambda s, k=key: self._set_orb_style(k))
                it.state = 1 if config.ORB_STYLE == key else 0
                style.add(it); self._orb_items[key] = it
            # Native-style menu: no emoji, grouped by separators (None), submenus for settings, dialog items end
            # with "…". Primary actions first, then history, settings, alarm status, setup, quit.
            self.menu = [
                "Talk to Sheru",
                "Type to Sheru",
                None,
                "History",
                None,
                voice,                 # Voice ▸
                mic,                   # Microphone ▸
                style,                 # Listening Style ▸
                "Mute",
                None,
                self._alarm_item,      # "No Alarms Set" / "<label> in <time>"
                self._stop_item,       # Stop Ringing
                None,
                "Grant Permissions…",
                "Set Up Spotify…",
                None,
                "Quit Sheru",
            ]

        def _set_voice(self, backend):
            from . import config
            config.set_tts(backend)
            self._voice_sarvam.state = 1 if backend == "sarvam" else 0
            for v, item in self._voice_items.items():      # a backend switch clears the specific-voice ticks
                item.state = 1 if (backend == "kokoro" and v == config.KOKORO_VOICE) else 0

        def _set_kokoro_voice(self, vid):
            from . import config
            config.set_kokoro_voice(vid)                    # sets the voice + switches to the local Kokoro backend
            for v, item in self._voice_items.items():
                item.state = 1 if v == vid else 0
            self._voice_sarvam.state = 0
            try:                                           # speak a short sample so you hear the new voice right away
                name = dict(config.KOKORO_VOICES).get(vid, vid).split("—")[0].strip()
                app.speaker.speak(f"This is {name}. How do I sound?")
            except Exception:
                pass

        def _set_orb_style(self, key):
            from . import config
            config.set_orb_style(key)
            try:
                app._ensure_orb()               # rebuild for the next activation
            except Exception:
                pass
            for k, item in self._orb_items.items():
                item.state = 1 if k == key else 0

        def _set_mic(self, device):
            from . import config
            from .audio import preferred_device
            config.set_mic(device)
            try:
                if app.listener is not None:
                    app.listener.stop()          # _stop clears both loops; then rebuild on the new device
            except Exception:
                pass
            app.start_voice()
            cur = preferred_device()
            for key, item in self._mic_items.items():
                item.state = (1 if device in (None, "") else 0) if key == "auto" else \
                             (1 if (device not in (None, "") and key == cur) else 0)

        @rumps.timer(2)
        def _tick(self, _):
            self._refresh_alarms()

        def _apply_symbol(self, name: str):
            """Set the status-item button to a white, theme-adapting SF Symbol (template image, modern button API)."""
            try:
                from AppKit import NSImage, NSImageSymbolConfiguration
                btn = self._nsapp.nsstatusitem.button()
                if btn is None:
                    return
                si = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, "Sheru")
                if si is None:                       # unknown symbol -> keep the 🦁 title so we're never blank
                    self.title = "🦁"
                    return
                cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_scale_(16, 5, 2)  # menu-bar sized
                si = si.imageWithSymbolConfiguration_(cfg)
                si.setTemplate_(True)                # template => white on dark bar / black on light, like native icons
                self.title = ""                      # the glyph carries identity; no text next to it
                btn.setImage_(si)
            except Exception:
                pass

        def _refresh_alarms(self):
            try:
                from . import alarms
                act = alarms.active()
                ringing = alarms.is_ringing()
                # The glyph is the mark; swap to a bell while an alarm rings. Apply only on change.
                want_sym = "bell.fill" if ringing else self._icon_symbol
                if want_sym != self._cur_sym:
                    self._cur_sym = want_sym
                    self._apply_symbol(want_sym)
                if ringing:
                    self._alarm_item.title = "Alarm Ringing"
                    self._stop_item.set_callback(lambda _: alarms.stop_ring())   # enable
                elif act:
                    n = act[0]
                    extra = f"  +{len(act) - 1} more" if len(act) > 1 else ""
                    self._alarm_item.title = f"{n['label']} in {alarms.human_remaining(n['remaining'])}{extra}"
                    self._stop_item.set_callback(None)                            # nothing to stop -> greyed
                else:
                    self._alarm_item.title = "No Alarms Set"
                    self._stop_item.set_callback(None)
            except Exception:
                pass

        @rumps.clicked("Talk to Sheru")
        def _talk(self, _):
            app.activate()

        @rumps.clicked("Type to Sheru")
        def _type(self, _):
            app.show_type_panel()

        @rumps.clicked("History")
        def _history(self, _):
            app.show_history_panel()

        @rumps.clicked("Grant Permissions…")
        def _grant(self, _):
            app.request_permissions()

        @rumps.clicked("Set Up Spotify…")
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
    def _prune_history():                          # expire conversations older than a week (unless starred)
        try:
            from . import conversations as _C
            n = _C.prune()
            if n:
                log.info("history: pruned %d old journal turns (kept starred + last week)", n)
        except Exception as e:
            log.debug("history prune skipped: %s", e)
    threading.Thread(target=_prune_history, daemon=True).start()
    def _perm_nudge():                              # if the .app isn't trusted, nudge once (hotkey/typing/auto-send)
        try:
            import time as _t
            _t.sleep(8)
            from . import permissions
            if not permissions.accessibility_trusted():
                import rumps
                rumps.notification("Sheru needs permissions", "Click '🔓 Grant Permissions' in the menu bar",
                                   "Enable Sheru under Accessibility + Automation so the F5 hotkey, auto-send, "
                                   "and typing mode work.")
        except Exception:
            pass
    threading.Thread(target=_perm_nudge, daemon=True).start()
    app.start_trigger_socket()
    if os.environ.get("SHERU_ALWAYS_ON"):
        threading.Thread(target=lambda: (_wait_warm(app), app.start_voice()), daemon=True).start()
    else:
        import sheru.hotkey as _hk
        # tap F5 -> orb + listen; HOLD F5 -> open the chat panel directly (F5 remapped->F18; needs Accessibility)
        ok = _hk.register(app.activate, on_hold=app.show_type_panel, key_code=_hk.KEY_F18)
        log.info("F18/F5 hotkey (tap=orb, hold=chat) via NSEvent: %s | also: `sheru trigger` (bind any key)", ok)
    if not is_done():
        from Foundation import NSTimer
        # show onboarding shortly after the run loop starts
        def _first_run(timer): app.show_onboarding()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.8, _OnceTarget.alloc().initWithFn_(_first_run), "fire:", None, False)
    # Hide the dock icon at RUNTIME, after the status item is laid out. Doing this via Info.plist LSUIElement (or
    # setting the policy before the run loop) makes the app an accessory from launch, which on Tahoe collapses the
    # status item to zero height (invisible). Setting Accessory a beat after launch keeps the menu-bar item.
    from Foundation import NSTimer as _NST
    def _hide_dock(timer):
        try:
            from AppKit import NSApplication
            NSApplication.sharedApplication().setActivationPolicy_(1)   # NSApplicationActivationPolicyAccessory
        except Exception:
            pass
    _NST.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.4, _OnceTarget.alloc().initWithFn_(_hide_dock), "fire:", None, False)
    sheru_app.run()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="sheru")
    p.add_argument("command", nargs="?", help="'setup' (first-run wizard) or 'trigger' (activate a running Sheru)")
    p.add_argument("arg", nargs="?", help="for 'trigger': 'chat' opens the type panel; default is voice")
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
            c.connect(str(config.DATA_DIR / "sheru.sock"))
            c.sendall(b"chat" if a.arg == "chat" else b"voice")   # tap -> voice, hold -> chat panel
            c.close()
            return 0
        except OSError:
            print("Sheru isn't running."); return 1
    # single-instance guard: if a Sheru is already running (its trigger socket accepts a connection), just ACTIVATE
    # it and exit — don't start a duplicate that fights over the mic + hotkey (looked like a crash / 'won't restart').
    if not a.text and not a.listen:
        import socket as _sk
        from . import config as _cfg
        try:
            _c = _sk.socket(_sk.AF_UNIX, _sk.SOCK_STREAM)
            _c.connect(str(_cfg.DATA_DIR / "sheru.sock")); _c.sendall(b"ping"); _c.close()   # probe, don't activate
            print("Sheru is already running. (Quit it from the menu bar first to fully restart.)")
            return 0
        except OSError:
            pass                                   # nothing listening (fresh start or a stale socket) -> proceed
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
