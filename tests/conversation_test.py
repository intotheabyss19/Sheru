"""Multi-turn CONVERSATION test — the thing the routing harness misses. Proves the 'continued conversation'
fixes: all-tier history, Claude session resume on follow-ups, recent-context injection on a fresh thread, and
silent local weather. Claude + audio are mocked, so nothing real runs.

Run: uv run python tests/conversation_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import sheru.net as net
from sheru.actions import weather

fails = []
def check(name, cond):
    print(("  ✓" if cond else "  ✗"), name)
    if not cond:
        fails.append(name)


class FakeClaude:
    """Stand-in for ClaudeSession: records each run's (task, resume) and answers instantly."""
    def __init__(self):
        self.session_id = None
        self.calls = []
        self._proc = None
    @property
    def busy(self):
        return False
    def run(self, task, on_sentence, on_done=None, on_error=None, resume=False, **kw):
        self.calls.append({"task": task, "resume": resume})
        self.session_id = "sess-123"
        on_sentence("Here is the answer.")
        if on_done:
            on_done("Here is the answer.")
        return None
    def cancel(self):
        return False


def main():
    net.online = lambda: True                     # force the Claude path (not offline fallback)
    weather.fetch = lambda city: "It's 20 degrees in Ravangla, partly cloudy."   # silent local weather, no network

    from sheru.app import Sheru
    app = Sheru(use_llm=False)
    app.claude = FakeClaude()
    app.journal.record = lambda **kw: None        # don't pollute the real journal
    app.router.say_async = lambda s: None         # no audio for "Checking the weather."
    app.speaker.speak = lambda *a, **k: None
    out = []
    sink = out.append

    print("TURN 1 — weather (silent local, no Claude)")
    app.handle_text("what's the weather", sink=sink)
    h = app.router.history
    check("weather answered locally (no Claude call)", len(app.claude.calls) == 0)
    check("weather reply spoken", any("degrees" in s for s in out))
    check("history recorded the weather turn (user+assistant)", len(h) == 2 and h[0]["role"] == "user")

    print("TURN 2 — news question -> Claude (fresh thread: resume False, context injected)")
    app.handle_text("summarize the news about ai", sink=sink)
    check("Claude was called once", len(app.claude.calls) == 1)
    check("first Claude turn does NOT resume", app.claude.calls[-1]["resume"] is False)
    check("recent context injected on fresh thread", "Context — earlier" in app.claude.calls[-1]["task"])
    check("history grew to 4 (news user + Claude answer)", len(h) == 4)
    check("Claude answer recorded in history", h[-1]["content"] == "Here is the answer.")

    print("TURN 3 — follow-up -> Claude (resume True, no context wrap)")
    app.handle_text("what about sports", sink=sink)
    check("Claude called again", len(app.claude.calls) == 2)
    check("follow-up RESUMES the session", app.claude.calls[-1]["resume"] is True)
    check("resumed turn sends raw task, no context block", "Context — earlier" not in app.claude.calls[-1]["task"])

    print("TURN 4 — song lookup must not hijack the conversation session id")
    saved = app.claude.session_id
    check("session id stable across turns", saved == "sess-123")

    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S): " + ", ".join(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
