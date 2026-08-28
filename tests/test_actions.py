"""Action-layer unit tests — the pure functions behind the tools (no side effects, no model).
Catches bugs the routing harness misses: app resolution, time parsing, URL/query building, arg extraction.
Run: uv run python tests/test_actions.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sheru.actions import apps, location, web  # noqa
from sheru import reminders                     # noqa
from sheru.router import Router                  # noqa

fails = []
def check(name, got, expect):
    if expect is None:
        ok = got is None
    elif isinstance(expect, str):
        ok = got is not None and expect.lower() in str(got).lower()
    else:
        ok = got == expect
    print(("  ✓" if ok else "  ✗"), f"{name:34} -> {got!r}")
    if not ok:
        fails.append((name, got, expect))

print("APP RESOLUTION")
check("resolve 'settings'", apps.resolve("settings"), "System Settings")
check("resolve 'the terminal'", apps.resolve("the terminal"), "Ghostty")
check("resolve 'whatsapp'", apps.resolve("whatsapp"), "WhatsApp")
check("resolve 'music'", apps.resolve("music"), "Spotify")
check("resolve 'browser'", apps.resolve("browser"), "Zen")
check("resolve 'obsidian'", apps.resolve("obsidian"), "Obsidian")
check("resolve gibberish", apps.resolve("qwzxlmnop"), None)

print("REMINDER TIME PARSING")
check("in 10 minutes", reminders.parse_when("call mom in 10 minutes")[0], 600.0)
check("in an hour", reminders.parse_when("x in an hour")[0], 3600.0)
check("in 30 seconds", reminders.parse_when("x in 30 seconds")[0], 30.0)
check("at 5 pm (positive)", reminders.parse_when("x at 5 pm")[0] > 0, True)
check("no time -> None", reminders.parse_when("just remind me")[0], None)

print("LOCATION")
check("describe is Ravangla", location.describe(), "Ravangla")
check("localize 'my location'", location.localize("weather at my location"), "Ravangla")
check("mentions_here", location.mentions_here("weather near me"), True)

print("MESSAGE ARG EXTRACTION (via router grammar)")
r = Router()
d = r.route("message bob that i'm running late").draft
check("recipient=bob", d and d["recipient"], "bob")
check("gist has 'running late'", d and d["gist"], "running late")
d2 = r.route("whatsapp raj that the meeting moved").draft
check("whatsapp app", d2 and d2["app"], "whatsapp")

print("SEARCH / URL BUILDING (state only, no browser)")
web._state["engine"] = "google"
check("engine set to google", web._state["engine"], "google")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURE(S): " + ", ".join(f[0] for f in fails)))
sys.exit(1 if fails else 0)
