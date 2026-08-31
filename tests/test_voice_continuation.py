"""Regression test for the LONG-standing 'continued conversation doesn't work' bug.

Root cause (2026-08-31): `_is_voice_sink` compared `sink is self._say_both` — a bound-method identity check that is
ALWAYS False (each `self._say_both` access is a new object), so every follow-up arm gated on it silently no-op'd.
This test imitates the voice loop (feeds commands via the VOICE sink) and asserts the mic RE-ARMS after each
command and STOPS after a sign-off — no mic/audio needed. Run: uv run python tests/test_voice_continuation.py
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheru.actions import apps, music, system, web, browser_agent, shortcuts, screen  # noqa: E402
_noop = lambda *a, **k: "ok"
for mod, fns in {
    apps: ["open_app", "quit_app", "switch_to"], music: ["play_song"],
    system: ["set_volume", "media", "change_volume", "mute", "window"],
    web: ["search", "image_search", "open_url", "site_search"],
    browser_agent: ["play_youtube", "play_music"],
}.items():
    for fn in fns:
        if hasattr(mod, fn):
            setattr(mod, fn, _noop)
shortcuts.run_shortcut = lambda *a, **k: None
screen.read_screen = lambda *a, **k: "Inbox"

from sheru.app import Sheru  # noqa: E402

app = Sheru(use_llm=False)                 # Tier-0 grammar only (no model load)
app.speaker.speak = lambda *a, **k: None   # no audio
app.journal.record = lambda *a, **k: None  # don't pollute the journal
app._record_turn = lambda *a, **k: None

fails = []


def check(name, cond):
    print(("  ✓" if cond else "  ✗ FAIL"), name)
    if not cond:
        fails.append(name)


def turn(cmd):
    app._followup_armed = False             # the loop clears this right before handle_text
    app.handle_text(cmd, sink=app._say_both)
    return app._followup_armed


check("_is_voice_sink(_say_both) is True (the bound-method fix)", app._is_voice_sink(app._say_both))
for cmd in ["what is five plus five", "open spotify", "search iphone 17 on amazon",
            "set volume to 30", "pause the music", "what's on my screen"]:
    check(f"keeps listening after {cmd!r}", turn(cmd))
check("STOPS listening after a sign-off ('no that's all')", not turn("no that's all"))

print(f"\n{'ALL PASS' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
