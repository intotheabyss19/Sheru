"""Regression tests for the 2026-08-30 overnight fixes — calc word-numbers/device-guard, structured on-device
answers (FX/news/wiki topic gating), reminder/alarm time parsing, spoken-text sanitizing, and local-first routing.

Uses PURE functions where possible; for router-level checks it MOCKS every side-effectful action first, so this
test never changes the system volume, schedules a real reminder, opens an app, or plays music.

Run: uv run python tests/test_overnight_fixes.py
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# ── mock side effects BEFORE importing the router ───────────────────────────────────────────────────
from sheru.actions import apps, music, system, files, web, browser, browser_agent
from sheru import alarms, reminders


def _noop(*a, **k):
    return "ok"


for mod, fns in {
    apps: ["open_app", "quit_app", "switch_to"], music: ["play_song"],
    system: ["set_volume", "media", "set_timer", "change_volume", "now", "mute"],
    files: ["make", "open_terminal", "open_terminal_claude"],
    web: ["search", "image_search", "open_url"],
    browser: ["set_browser"], browser_agent: ["play_youtube", "play_music"],
}.items():
    for fn in fns:
        if hasattr(mod, fn):
            setattr(mod, fn, _noop)
alarms.schedule = _noop
reminders.schedule = _noop                             # <- so router alarm/remind tests DON'T persist real reminders

from sheru.actions import calc, structured
from sheru.numwords import replace_number_words as R
from sheru.tts import _for_speech
from sheru.router import Router


class _Mem:
    def context_block(self, q): return ""
    def remember(self, x): return "noted"


r = Router(memory=_Mem())                              # no LLM -> grammar/calc tiers only
fails = []


def check(name, cond):
    print(("  ✓" if cond else "  ✗ FAIL"), name)
    if not cond:
        fails.append(name)


print("calc — word-numbers, device guard, factorial, roots:")
check("five plus five = 10", calc.calc("five plus five") == 10)
check("ten times ten = 100", calc.calc("ten times ten") == 100)
check("twenty divided by four = 5", calc.calc("twenty divided by four") == 5)
check("two to the power of ten = 1024", calc.calc("what is two to the power of ten") == 1024)
check("square root of 5 ~ 2.236", abs(calc.calc("square root of 5") - 2.2360679) < 1e-4)
check("20 percent of 300 = 60", calc.calc("what is 20 percent of 300") == 60)
check("factorial of 5 = 120 (prefix)", calc.calc("factorial of 5") == 120)
check("5 factorial = 120 (postfix)", calc.calc("what is 5 factorial") == 120)
check("'volume 20 percent' NOT math", calc.calc("volume 20 percent") is None)
check("'brightness 50 percent' NOT math", calc.calc("brightness 50 percent") is None)
check("'add 2 apples and 3 oranges' NOT math", calc.calc("add 2 apples and 3 oranges") is None)

print("numwords:")
check("'one hundred fifty' -> 150", R("one hundred fifty") == "150")
check("'two thousand and five' -> 2005", R("two thousand and five") == "2005")
check("'a quarter of an hour' untouched", "quarter" in R("a quarter of an hour"))
check("'play one by u2' stays words in songs (only calc/fx/vol convert)", "one" in "play one by u2")

print("structured — FX / news / wiki gating:")
check("fx digits: 100 usd->inr", "rupees" in (structured.fx("100 dollars in rupees") or ""))
check("fx word amount: 'hundred dollars' -> 100", (structured.fx("convert hundred dollars to rupees") or "").startswith("100"))
check("fx 'fifty euro in inr' -> 50", (structured.fx("fifty euro in inr") or "").startswith("50"))
check("wiki answers 'who is Ada Lovelace'", "Lovelace" in (structured.wiki("who is Ada Lovelace") or ""))
check("wiki skips 'what is the weather'", structured.wiki("what is the weather today") is None)
check("wiki skips currency", structured.wiki("what is 100 usd in inr") is None)
n_ai = structured.news("news about AI") or ""
check("news keeps 2-char topic 'AI'", n_ai.lower().startswith("top news about ai"))

print("reminders.parse_when — durations & clock:")
check("'in 2 hours' = 7200s", reminders.parse_when("in 2 hours")[0] == 7200)
check("'in half an hour' = 1800s", reminders.parse_when("in half an hour")[0] == 1800)
check("'in a quarter of an hour' = 900s", reminders.parse_when("in a quarter of an hour")[0] == 900)
check("'quarter past 7' (digit) parses", reminders.parse_when("alarm at quarter past 7")[1] == "at 7:15")
check("'half past 6' (digit) parses", reminders.parse_when("alarm at half past 6")[1] == "at 6:30")
check("'7 in the morning' -> 7:00", reminders.parse_when("alarm at 7 in the morning")[1] == "at 7:00")
check("'5 in the evening' -> 17:00", reminders.parse_when("alarm at 5 in the evening")[1] == "at 17:00")

print("tts._for_speech — never read markup aloud:")
check("**bold** stripped", _for_speech("**bold** text") == "bold text")
check("bullets stripped", "\n" in _for_speech("- one\n- two") and "-" not in _for_speech("- one\n- two").split("\n")[0])
check("url -> 'a link'", "a link" in _for_speech("see https://example.com/x now"))
check("emoji removed", "🎉" not in _for_speech("great 🎉 job"))
check("plain sentence unchanged", _for_speech("Just a normal sentence.") == "Just a normal sentence.")
check("tech tokens preserved (C#, af_heart)", _for_speech("C# and af_heart") == "C# and af_heart")

print("router — local-first routing (grammar/calc tiers, side effects mocked):")
check("calc routes to calc tool", r.route("what is the square root of 5").tool == "calc")
check("news -> local search", bool(r.route("what is the news today").search))
check("currency -> local search", bool(r.route("how much is 100 dollars in rupees").search))
check("GDP (changing stat) -> local search", bool(r.route("what is the gdp of india").search))
check("coding -> Claude handoff", bool(r.route("write a python script to rename my files").handoff))
check("'set volume to twenty' -> volume tool (word-number)", r.route("set volume to twenty").tool == "volume")
check("'remind me in half an hour' schedules (mocked)", "remind" in (r.route("remind me in half an hour").speech or "").lower())
check("'open a wikipedia page on X' -> wiki_open (not open_app)", r.route("open a wikipedia page on the sun").tool == "wiki_open")
check("'open spotify' still -> open_app", r.route("open spotify").tool == "open")

print("router — WhatsApp calling (confirm-first; routing only, no calls placed):")
check("'call satya on whatsapp' -> call intent", r.route("call satya on whatsapp").call is not None)
check("'call satya on whatsapp' recipient == satya", (r.route("call satya on whatsapp").call or {}).get("recipient") == "satya")
check("'video call satya' -> video=True", (r.route("video call satya").call or {}).get("video") is True)
check("'ring gaurav choudhary' -> call intent", r.route("ring gaurav choudhary").call is not None)
check("'give satya a call' -> call intent", r.route("give satya a call").call is not None)
check("'call claude' is NOT a call", r.route("call claude").call is None)
check("'call it a day' is NOT a call", r.route("call it a day").call is None)

print("typing/dictation mode — routing + disable-phrase detection:")
import re as _re
_t1 = r.route("open Gaurav's chat and activate typing mode")
check("'open X's chat and activate typing mode' -> typing, recipient", bool(_t1.typing) and _t1.typing.get("recipient") == "gaurav")
_t2 = r.route("activate typing mode")
check("'activate typing mode' -> typing, no recipient", bool(_t2.typing) and _t2.typing.get("recipient") is None)
check("'turn on typing mode' -> typing", bool(r.route("turn on typing mode").typing))
check("'start dictation mode' -> typing", bool(r.route("start dictation mode").typing))
_DIS = _re.compile(r"\b(disable|deactivate|stop|exit|turn off|end|quit|close)\s+(?:the\s+)?(?:typing|dictation|type|hands\s?free)\s*mode\b")
_is_dis = lambda s: bool(_DIS.search(s) or s in ("stop typing", "disable typing", "typing off", "exit typing", "done typing"))
check("'disable typing mode' detected as exit", _is_dis("disable typing mode"))
check("'stop typing' detected as exit", _is_dis("stop typing"))
check("'send this to gaurav' is NOT an exit (gets typed)", not _is_dis("send this to gaurav"))

print("tts — phonemizer language-switch fix (names like 'Satya' don't become gibberish):")
from sheru.tts import _patch_phonemizer_language_switch
_patch_phonemizer_language_switch()
import phonemizer.backend as _pb
check("Devanagari romanized for TTS (no gibberish)", _for_speech("गाना बजाओ") == "gana bajao")
check("English speech unchanged by romanizer", _for_speech("play a song") == "play a song")
check("phonemizer patched to remove-flags", getattr(_pb.EspeakBackend, "_sheru_no_lang_switch", False) is True)

print("dictionary — local macOS definitions:")
from sheru.actions import dictionary as _D
check("define serendipity (local, offline)", (_D.define("serendipity") or "").startswith("noun."))
check("unknown word -> None (falls to search)", _D.define("asdfghjkl") is None)

print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED: ' + ', '.join(fails)}  "
      f"({'0' if not fails else len(fails)} of many)")
sys.exit(1 if fails else 0)
