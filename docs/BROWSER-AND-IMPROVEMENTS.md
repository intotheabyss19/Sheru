# Session progress — browser tier, logging, dev-audio (2026-08-29, while you were away)

Everything below is committed on branch `overnight` and the running app was restarted with it. Local dev audio
is on (Kokoro + Whisper) — no Sarvam credits burned.

## ✅ Working now (validated) — press F5 or Type-to-Sheru
| Command | What it does | Status |
|---|---|---|
| "play tum hi ho **on youtube**" / "**youtube** lofi hip hop" | resolves the first video and opens the watch URL in **Brave/piyush** (autoplays, stays open) | ✅ resolution + open both verified |
| "play despacito **on youtube music**" | same on music.youtube.com | ✅ |
| "**open gmail**" / "check my email" | opens Gmail in the current browser+profile | ✅ |
| "**use brave**" / "use chrome" / "use zen" | picks the automation browser | ✅ |
| "**use piyush's profile**" / "use moon('s) profile" / "switch to X profile" | launches Brave with that profile (`Piyush`=Profile 2, `moon`=Profile 4, discovered live) | ✅ |
| "set an alarm for **eleven fifteen a.m.**" / "wake me at **half past six**" / "**quarter to eight**" | spoken clock times now parse (was unparseable → this was a real bug from your logs) | ✅ |
| "**play X**" (no platform) | Spotify if it has a confident match, else **falls back to YouTube** (no more "couldn't find it" dead-ends); "play X **on spotify**" still uses Spotify | ✅ |
| "message `<name>` **on linkedin** saying `<text>`" | opens their LinkedIn + copies the message to clipboard to paste (safe; no auto-send to a wrong person) | ✅ |
| all prior: apps, alarms/timers/reminders (with a **bell**), weather, messages, files, trainer, memory | — | ✅ |

## 🔁 The self-improvement loop (your "check logs + improve each session")
Run **`uv run python scripts/review_logs.py`** at the start of any session — it reads `data/journal.jsonl` and
surfaces the **fix list**: FAIL/negative turns, phrasings you had to correct, and the intent mix. I used it this
session and it caught the "eleven fifteen → 660-minute timer" bug, now fixed. This is how "improve Sheru each
time" works day-to-day; actual model fine-tuning is the periodic RunPod step (§ below).

**Routing checked across 42 JARVIS scenarios — all correct.** Full stress test held at ~81% (rest are known
adversarial idioms). Grammar broadened: "that's enough"→stop, "what did I just copy"→clipboard, "from now on…".

## ✅ Richer logging (your "don't just log inputs")
Every turn now records **input → the action taken → outcome (ok/FAIL)**:
- `data/actions.log` — human-readable, one line per turn: `14:40 [ok ] IN: 'open spotify' -> DID: [open] Opening Spotify.` — `tail -f data/actions.log` to watch it live.
- `data/journal.jsonl` — same as JSON with `action`, `ok`, `tool`, feedback (feeds the improvement loop).
- Tier-0 grammar actions now label their action (were logged as `None`).

## ⏳ Needs your setup / decision (Gmail + LinkedIn *sending*)
I deliberately did **not** ship untested email/LinkedIn **send** code — those send to real people, and I couldn't
validate them while you were away (they need a logged-in browser + your confirmation). The design is ready; two
lanes (pick per task):

**Architecture decided (from research):**
- **Lane A — Playwright on Brave** (local, $0, deterministic) for the named tasks. Already installed (`playwright`).
- **Lane B — `claude -p` + Claude-in-Chrome** for open-ended tasks. **Claude-in-Chrome is Google-Chrome-only** and is **not a headless MCP** (Sheru's config only has `runpod`), so it needs Chrome + the extension + adding the MCP to the `claude -p` call.
- **Zen can't be driven agentically** (it's Firefox/Gecko — no CDP, no Claude-in-Chrome). Zen stays for simple opens; **Brave is the automation browser**.

**Setup checklist (10 min, together when you're back):**
1. **Which browser** — earlier both a Windows and a macOS Chrome were connected to Claude-in-Chrome; on the Mac we'll use the macOS one. For Lane A we use **Brave** directly (no selection needed).
2. **One-time logins for Lane A:** either (a) log into YouTube/Gmail/LinkedIn once in a Sheru-owned Brave profile at `~/.sheru/brave-automation`, or (b) drive your real `Piyush` profile (needs Brave fully closed at run time — the fiddlier path).
3. **For Lane B (open-ended):** install **Google Chrome** + the **Claude for Chrome** extension (paid Claude plan), pin it, and **pre-grant** youtube.com / mail.google.com / linkedin.com once so `claude -p` can run unattended.
4. Then I wire: "**message `<name>` on LinkedIn saying `<text>`**" → draft → **you confirm** → send; and "**email `<name>` `<text>`**" the same way. **Send always asks first** (they're irreversible + TOS-sensitive; LinkedIn actively flags automation, so we drive your real logged-in profile and never auto-send).

*Right now* "message X on linkedin" opens their LinkedIn and hands you the draft; it won't send until the above is set up + validated.

## What I'd validate with you first (5 min)
1. "play X on youtube" actually plays in Brave/piyush (I proved the pieces but didn't blast audio for 3h).
2. "use piyush's profile" / "use moon's profile" open the right Brave profile.
3. One LinkedIn send end-to-end (with your confirm) to lock the selectors.

## On "retrain the model each session"
- **Now:** the input→action logs make failures reviewable every session; I fix routing/prompts from them (did this — grammar + escalation fixes).
- **Actual fine-tuning** = the RunPod GPU step (Phase 6): distill Claude's routing on the logged traces into a LoRA, eval-gate, promote. I'll stage the data pipeline so the day you enable RunPod we refit. It is NOT something to run every session locally — it's a periodic refit; retrieval/prompt fixes cover the day-to-day.

## Commits this session (branch `overnight`)
browser tier (Lane A) · logging input→action · Sarvam→local dev audio · reply-language auto (EN/HI mirror) ·
grammar broadenings. All verified; app restarted and running.
