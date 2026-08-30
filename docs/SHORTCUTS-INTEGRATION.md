# Shortcuts integration — OVERNIGHT BUILD QUEUE

**Status:** queued for an overnight session (Yash: "note em down, you'll build em in the overnight session", 2026-08-30).
**Core idea:** Sheru can call `shortcuts run "<name>"` to borrow ANY macOS Shortcuts action it can't do natively.
Shortcuts is the bridge to system controls that are painful/impossible to script from Python/osascript. Add ONE
bridge tool + a small set of helper shortcuts and Sheru's system-control reach expands massively, $0, robust.

Source of the action inventory: `https://blakecrosley.com/guides/shortcuts` (Yash shared it).

---

## Build order (highest leverage first)

### 1. The `run_shortcut` bridge — do this FIRST (unlocks everything else)
One tool + grammar that shells out to the Shortcuts CLI. Every helper shortcut then becomes a Sheru capability
with no new code.

- **Action** (`actions/shortcuts.py`, new):
  ```python
  import subprocess
  def run_shortcut(name: str, text: str | None = None) -> str:
      """Run a macOS Shortcut by name via the `shortcuts` CLI. Optional stdin text. Alert-free shortcuts only
      (an input prompt hangs the process). Returns stdout, or '' on success with no output."""
      try:
          r = subprocess.run(["shortcuts", "run", name] + (["-i", "-"] if text else []) + (["-o", "-"] if text else []),
                             input=(text or None), capture_output=True, text=True, timeout=20)
          return (r.stdout or "").strip() if r.returncode == 0 else ""
      except Exception:
          return ""
  def list_shortcuts() -> list[str]:
      r = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10)
      return [l.strip() for l in r.stdout.splitlines() if l.strip()]
  ```
- **Grammar (Tier 0):** `"run shortcut X"`, `"run the X shortcut"`, `"shortcut X"` → `run_shortcut(X)`.
  Fuzzy-match X against `list_shortcuts()` (rapidfuzz, already a dep) so STT spelling wobble still hits.
- **Gotcha:** the Shortcuts *Run Shell Script* action needs Settings → Shortcuts → Advanced → **Allow Running
  Scripts** ON. Alert/ask-for-input shortcuts hang the CLI — keep helper shortcuts silent + input-free.
- **Discoverability:** on startup, log the user's shortcut names so routing can prefer real ones.

### 2. Set Focus / Get Current Focus ⭐ — the top gap
Focus/Do-Not-Disturb has no clean scripting API; Shortcuts `Set Focus` / `Get Current Focus` are the only sane path.
- Helper shortcuts to create (or auto-create if the CLI/AppleScript allows): `Sheru Focus On` (param: mode),
  `Sheru Focus Off`, `Sheru Get Focus`.
- **Sheru commands:** "turn on Do Not Disturb", "switch to Work focus", "turn off focus", "am I in a focus?".
- **Bonus behavior:** Sheru reads current Focus (via the Get-Focus shortcut) and **stays quiet / defers spoken
  replies** while a Sleep/DND focus is on — a real JARVIS touch. Wire into the TTS gate.

### 3. Window management (mouseless, by voice)
Shortcuts `Move Window`, `Resize Window`, `Split Screen Apps` — Sheru has no window control today.
- **Sheru commands:** "move this window left", "make it full screen", "split these side by side", "center this window".
- Map spoken directions → helper shortcuts (`Sheru Window Left/Right/Full/Center`, `Sheru Split`). Targets the
  frontmost window.

### 4. On-device OCR via `Extract Text from Image`
A free, instant screen-read path callable from the CLI — feeds the vision goal without building the Apple Vision
layer yet.
- Flow: `screencapture` → pass the PNG to a helper shortcut wrapping `Extract Text from Image` → read stdout.
- **Sheru commands:** "what does this say on screen?", "read this to me".

### 5. Personal Automations → PROACTIVE Sheru
Automations fire on time-of-day, app open/quit, battery level, charger, Focus change, Wi-Fi/Bluetooth. Wire one to
run a Sheru command and Sheru gains proactivity. Design a small default set + a way for Sheru to register them:
- battery < 20% → Sheru warns by voice.
- a set time (e.g. 11pm) → Sheru enables Sleep focus + lowers volume.
- a specific app opens → Sheru does X.
- These are user-created automations that call `sheru trigger`-style commands or Sheru-owned shortcuts. Sheru's
  socket already accepts external triggers — extend the protocol so an automation can pass an intent string.

**Skip:** `Use Model` (Apple Intelligence) — redundant with Sheru's local LLM + Claude. Wi-Fi/Bluetooth *set*
actions aren't reliably present on Mac (only listed as automation *triggers*) — don't promise toggling those.

---

## ALSO QUEUED (overnight): repackage Sheru.app as a PROPER bundle — fixes the menu-bar icon
**Root cause (diagnosed 2026-08-31):** `/Applications/Sheru.app/Contents/MacOS/Sheru` is a bash shim that
`exec`s `/Users/yash/Projects/Sheru/.venv/bin/sheru` — a binary *outside* the bundle. macOS then treats the
running python as a **faceless/background process** with no proper GUI app identity, so the rumps `NSStatusItem`
lays out with **zero height** (button exists, title/image set, `isVisible=True`, but `window.frame` height=0 →
invisible). The exact same code shows the glyph fine when launched from a terminal (inherits the Aqua GUI
session) or as a bare rumps app. Removing `LSUIElement` + runtime `setActivationPolicy` do NOT fix it; promoting
to Regular makes it visible but steals focus / shows an empty menu bar. Confirmed via bare-rumps A/B tests.

**Fix:** build a real bundle whose executable lives inside `Contents/MacOS` (py2app, or a bundled python +
`__boot__` that runs `sheru.app:main`), so LaunchServices gives it proper app identity. Then the menu-bar SF
Symbol (sparkles, already wired) shows on normal `.app` launch, and the existing runtime Accessory demotion drops
the dock icon. **Verify:** launch via `open -a Sheru`, confirm the sparkles glyph renders and no dock icon; re-check
mic/Accessibility TCC (a re-signed/rebuilt bundle = new cdhash may need re-granting). Interim today: Sheru is run
from the shell (`nohup .venv/bin/sheru`) which shows sparkles but does NOT survive reboot — the login-item `.app`
still hides it until repackaged.

## Also useful, callable via the same bridge (lower priority)
`Get Text from PDF`, `Make PDF`, `Get Details of Appearance` (dark-mode state), `Get Network Details` /
`Get Current IP Address`, `Get Items from RSS Feed`, `Find/New Reminder`, `Find Calendar Events`,
`Create New Note` — most Sheru already does natively; only add if a native path is missing or fragile.

---

## FUTURE (NOT this overnight) — native "Hey Sheru" wake word
Deferred per Yash ("let it be a future thing for now"). Two routes, both validated to reach `sheru trigger`
(absolute socket, works from any cwd):
- **Route A — Vocal Shortcuts → Siri Request → a "Wake Sheru" shortcut** (needs Siri *enabled*, unused). Light,
  doesn't hijack dictation. On Tahoe, Vocal Shortcuts only offers Siri Request + Accessibility toggles — no direct
  Run-Shortcut, so it must route through Siri.
- **Route B — Voice Control → Custom Command → Run Workflow** (no Siri, but takes over the mic; conflicts with
  Sheru's PTT). Also: Voice Control's Grid/Number overlay = free mouseless clicking.
- When picked up: build an **Automator "Wake Sheru" Quick Action** (`.workflow` with the `sheru trigger` shell
  line) — Automator has no "Allow Running Scripts" gate, so it's the clean artifact for Route B.
- Reality check: neither beats the F5 tap on latency; the native wake word is a convenience with a lag/Siri cost.
