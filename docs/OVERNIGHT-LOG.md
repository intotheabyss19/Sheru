# Overnight work log — for Yash (waking ~9am)

Autonomous session: improve Sheru + GUI, add personality, fix issues, test, research, fine-tune.
Times are local. Newest at the bottom.

---

## 🌅 Sep 1 — latest session (READ THIS FIRST)

Big session. Sheru is currently **OFF** (you asked me to keep it off; I only started it briefly for tests). To
turn it back on: menu-bar isn't there while it's off — run `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sheru.assistant.plist`, or just tell me.

**★ Your VRAM question:** yes — while idle (just waiting for F5), Sheru keeps its models resident in **unified
memory (~5–6 GB)** so activation is instant; it does NOT unload between uses. **Quitting frees all of it** (menu
▸ Quit, or the new Settings ▸ Quit button). Measured: quitting jumped free memory 34% → 63%.

**★ Audio — fully overhauled (your biggest pain):**
- **Mic garbling fixed.** Root cause was resampling the 48 kHz mic **per-block** (stateless) → distortion. Now a
  stateful streaming resampler (proven 0.0000 error). Plus Apple **Voice-Processing I/O** (AEC/AGC/noise-suppress).
- **Talkback loudness fixed.** Three things: the mic engine was **ducking** Sheru's own voice (set to Min now);
  Kokoro renders at −27 dBFS (now loudness-normalized to −14); and a **soft limiter** removed the "stretched" edge.
- **Mic no longer always-on.** It's released when a conversation ends (the orange indicator was staying lit — my
  regression, fixed). **Voice/noise:** for off-axis background noise, turn on **Control Center ▸ Mic Mode ▸ Voice
  Isolation** while Sheru listens (macOS won't let apps set it; it's a one-time toggle that sticks).
- Hallucination + prompt-echo gates so silence/noise stops producing phantom commands.

**★ Voices, cues, close phrases, latency:**
- **8 local male voices** + a picker (Michael/Adam/Onyx/Eric US, George/Lewis/Daniel UK, Omega Hindi). Default now Michael.
- **Sound cues** are clean **high sine chimes** now (rising = your turn, falling = mine), with themes.
- **Close the conversation by voice:** "bye sheru", "quit sheru", "stop listening", "go to sleep", "we're done", etc.
- **Latency:** first reply is instant now (Kokoro pipeline pre-warmed; was a ~3 s cold gap); follow-up mic re-opens ~0.8 s sooner.

**★ Personality — de-tea'd.** The "JARVIS" framing was steering it into tea/butler tropes (you pushed back a lot in
the logs). Rewrote it to "warm, natural, light — no recurring bits", explicitly no tea. Added an editable
**`data/preferences.md`** Sheru reads live — write your tone/preferences there (or in Settings) and it adapts, no restart.

**★ Settings GUI (new).** Menu bar ▸ **Settings…** opens a real window: voice + loudness/speed, mic, orb style +
custom image, sound-cue theme, reply language, the **preferences editor**, "open a trainer session", and **Quit
(free memory)**. The menu bar is now minimal. (Custom-orb-image is stored but not yet rendered — follow-up.)

**★ huihui experiment (you asked me to try both):**
- **Text abliterated** (`Josiefied-Qwen3-4B-abliterated`): **74%** on the router eval vs base **76%** → *fails the
  gate, kept base.* Abliteration slightly hurts tool-routing, as expected. The over-refusal you wanted gone was
  fixed by the prompt rewrite instead.
- **Vision abliterated** (`huihui Qwen3-VL-4B-Instruct`, MLX 4-bit): **excellent.** Read a test UI **verbatim** and
  grounded buttons by colour+position ("the green Send button is on the right"). This is the one worth adopting —
  it's the engine for the screen-vision idea (read screen / click by label). Runs in an isolated env (~2.5 GB).
  Details + next steps in `docs/BACKLOG.md` ▸ Local models.

**⚠️ One honest thing:** while screenshotting the Settings window to check its layout, I captured your **live screen**
(you were on a video call) instead of the window. I deleted it immediately, didn't use it, and switched to rendering
the window **off-screen** (never touches your display). Won't happen again.

**Test when you're up:** press F5, have a back-and-forth (louder, cleaner, male voice), say "bye sheru" to end;
open **Settings…** and try the voices/cues; edit `preferences.md`. All committed + pushed on `overnight`+`main`.

---

## Aug 31 — earlier session
**Sheru is live** on the base 2507 model with a **✦ sparkles** menu-bar icon that now **auto-starts at login and
survives reboots** (runs as a LaunchAgent — the old `.app` couldn't show an icon due to a faceless-process bug).

**What's new since last night:**
- **Real bugs you hit — fixed:** "set volume to 20%" (the LLM was faking it; now actually sets it), "how do you
  feel about me" (was a bogus YouTube "tutorial"), mic **locked to your built-in** over the headset.
- **New system control:** **"run shortcut &lt;name&gt;"** runs any Shortcut · **Focus/DND** ("turn on do not disturb",
  "set focus to work", "what's my focus") · **brightness** ("set brightness to 50", "dim the screen") · **window
  management** ("maximize this window", "left half", "center this window" — works now, via Rectangle).
- **Fine-tune retry:** bigger, honest dataset + fresh LoRA on 2507 → still overfit; **kept base** (84% vs adapter ≤76%).
- **★ Reliability fixes (your #1 complaint):** two code audits found + fixed ~11 real bugs — the biggest: **a handler
  crash used to silently kill the whole voice loop** (mic just closed → "it stopped for no reason"); now it survives
  and says so. Also: "remind me to check the weather" / "text mom the weather looks bad" no longer misroute to a
  weather lookup; a half-finished message draft no longer hijacks your next command; "stop it" now cancels Claude.
- **★★ Audio overhaul — "how Siri does it" (your garbling/looping question):** Sheru's mic now runs through Apple's
  **Voice-Processing engine** — the same front-end Siri/FaceTime use: **echo cancellation** (Sheru's own voice can't
  re-trigger or garble it), **auto gain** (no more clipping — this retires the old mic-volume hack that was *causing*
  the garbling), and **noise suppression**. On top, a **3-layer anti-hallucination gate** so it stops inventing
  phantom speech on silence (Whisper's canned "Thank you." / "I'm sorry." loops): it now says **"no speech captured"**
  and closes cleanly instead of spinning. Verified live end-to-end. Falls back to the old mic path automatically if
  the engine can't start. *This is the fix for the recurring "it keeps listening / garbles / won't stop" problem.*

**⚙️ Your ~2-minute setup to unlock the rest:**
1. Menu-bar **✦ → 🔓 Grant Permissions** → enable Sheru under **Accessibility** + **Microphone** (it's a new
   login-agent identity, so it re-asks). Without this the F5 hotkey / typing / auto-send stay off.
2. In the **Shortcuts app**, create 4 shortcuts to power Focus + brightness by voice: `Sheru Set Focus`,
   `Sheru Focus Off`, `Sheru Get Focus`, `Sheru Set Brightness` — exact steps in `docs/SHORTCUTS-INTEGRATION.md`.
   (Window management + "run shortcut X" already work with no setup.)

Full details + from-when-to-when tables below (newest at the bottom).

## TL;DR (good morning ☀️)
- **Theme: made Sheru far more LOCAL-first** (your core success bar). Informational questions, currency,
  weather, news, "who/what is X", and changing stats (GDP/population) now answer **on-device** — verified
  6/6 real escalations from your usage log now resolve locally, no Claude.
- **New on-device answerers**: exact FX (Frankfurter), weather (Open-Meteo + your location), news (Google
  News RSS), Wikipedia — plus a DuckDuckGo-lite fallback so a blocked endpoint doesn't force a Claude call.
- **Personality/pride** added to Sheru's system prompt (JARVIS-like, proud to be local).
- **Bugs fixed** (all found by testing + a fresh code audit, all verified): calc hijacking "volume 20 percent";
  spoken **number-words** ("five plus five", "convert hundred dollars") now work in calc/FX/volume; alarm/reminder
  parsing ("7 in the morning", "half an hour", "quarter past 7"); reminders keeping context ("...at the store");
  long answers cut off; **TTS no longer reads markdown/emoji aloud** ("asterisk asterisk").
- **Fine-tune**: ran a local LoRA, built an eval-gate, **kept the base model** — the adapter overfit and would
  have hurt (regressed chat + sent search to Claude). Details in `docs/FINETUNE-RESULT.md`. This is the correct,
  honest outcome; a real (non-synthetic) dataset is the next step if you want to retry.
- **Housekeeping**: Apache-2.0 license, ~18 focused commits on `overnight` (FF-merged to `main`, both pushed).
  **Sheru is running on the base model with all fixes live.** Nothing left playing/open from testing.
- **Try when you wake**: broken-English commands, "what's 100 dollars in rupees", "who is <someone>",
  "what's the news", "set an alarm for 7 in the morning", "five times five", "remind me in half an hour",
  "open a wikipedia page on black holes".
- ⚠️ **Heads-up: I left system volume at 8%** (your "≤10% during testing" rule) — turn it up to hear Sheru.

| Start | End | What I did | Result |
|---|---|---|---|
| 04:20 | 04:41 | Broken-English routing stress test (mocked, no real side effects) + fixes: 'stop the music' now pauses (was cancel), Hinglish 'bajao', 'make it loud'/'turn down sound', 'what time now', 'pics of X' | 6 misroutes fixed, no regressions |
| 04:41 | 04:44 | 'start a timer/alarm' → open-app misroute fixed; calc no longer fires on non-math ('add 2 apples and 3 oranges') | 2 real bugs fixed |
| 04:44 | 04:47 | Personality/pride added to Sheru's system prompt (confident, warm, JARVIS-like, proud to be local) | Live |
| 04:47 | 04:52 | 3 research agents (MLX fine-tuning, local-first techniques, codebase review) → acted on findings | Reports in hand |
| 04:47 | 04:52 | ★ Tier-1 routes info questions to LOCAL search (was Claude) + look_up tool — biggest local-first win | Verified: PM/population/iphone stay local, coding→Claude |
| 04:52 | 05:03 | Structured on-device answers: FX (Frankfurter), weather (Open-Meteo + your location), news (Google News RSS) — tried before scrape+summarize | Verified live: '$100→₹9539', 'weather→26° thunderstorms', news headlines. All local, no key, no LLM |
| 05:03 | 05:06 | decide() bug fixes: max_tokens 160→256 (long answers were cut off); never speak raw tool-call JSON/tags — escalate instead | Live |
| 05:06 | 05:11 | Audited real overnight usage log: 6 failures (euro→INR, $→₹, factorial 50, √5, SBI price, GDP) all now resolve ON-DEVICE (calc + structured FX + scrape). Verified end-to-end | 6/6 local, 0 regressions |
| 05:11 | 05:16 | Wikipedia structured answers: 'who is X'/'what is X'/'tell me about X' → crisp local 2-sentence facts (keyless REST). fx/weather/news still win for live data | Verified: Ada Lovelace, black hole, Turing all local |
| 05:15 | (running) | Started local LoRA fine-tune (Qwen3-4B-4bit, 8 layers, 400 iters, seq 2048) — app stopped to free RAM. Will eval-gate: deploy only if it beats base | val loss 2.32→0.023 @iter50; gate pending |
| 05:16 | 05:18 | Search robustness: DuckDuckGo Lite fallback so a blocked/changed HTML endpoint degrades locally instead of escalating to Claude | Verified: 13 lite results when HTML forced-fail |
| 05:18 | 05:21 | Fine-tune plumbing: serve LoRA adapter without fusing (config.LOCAL_ADAPTER) + eval_router.py held-out gate (deploy only if beats base) | Ready for post-training gate |
| 05:21 | 05:24 | Fixed 2 alarm/reminder bugs found by testing: 'N in the morning/evening/night' now parses; 'remind me in 2 hours' no longer garbled | Verified 8/9 phrasings |
| 05:24 | 05:28 | Route changing stats (population/GDP/net worth) to local search — model's memory is stale (real log: GDP answered as $2.7T) | Verified: stats→local, timeless facts→chat |
| 05:28 | 05:31 | TTS spoken-text sanitizer: markdown/code/URLs/emoji no longer read aloud (Claude & search replies are markdown) | Verified 8 samples, tech tokens preserved |
| 05:31 | 05:39 | Ran a fresh code-audit agent (verified findings by executing code) → fixed 7 real bugs: calc hijacking 'volume 20 percent'→0.2, reminders dropping 'at the store'/'in accounting' context, 'half/quarter of an hour' silently refused, 'quarter past 7' (digit) failing, news dropping 2-char topics ('AI'), weather not falling back to Open-Meteo, postfix '5 factorial' | All 7 verified fixed, 0 regressions |
| 05:39 | 05:52 | Word-numbers (Whisper emits them): new numwords.py + wired into calc ('five plus five'=10), FX ('convert hundred dollars'=100), volume ('set volume to twenty'=20). Scoped so songs/messages stay untouched | Verified + regression-checked |
| 05:15 | 05:52 | Local LoRA fine-tune ran to iter 200 (converged: val loss 2.32→0.012, plateaued by iter 100). Built eval-gate, evaluated base vs adapter-100 vs adapter-200 on held-out novel/broken-English utterances | **KEPT BASE** — adapters overfit: iter100 regressed chat-negatives + confused tools (open→play); iter200 broke local-first (sent search→Claude) + hallucinated a `create_folder` tool. Base: 79%, chat 6/6, all search cases correct. Eval-gate worked as designed |
| 05:52 | 05:54 | Restarted Sheru on the base model with all tonight's fixes live | App RUNNING, models warm 4.4s |
| 05:54 | 05:56 | **Cleanup after testing** (as you asked): my router tests had actually executed side effects — reset system volume 100%→8% (a "make it loud" test cranked it) and cleared 11 stale test reminders (one would've rung a bell at 5pm). Verified clean restart: no restored reminders, no audio errors | System left tidy, volume 8% |
| 05:56 | 06:02 | Wrote tests/test_overnight_fixes.py — 36 side-effect-free regression checks locking in tonight's fixes (mocks all actions so it never changes volume/schedules reminders) | All 36 pass, 0 side effects |
| 06:19 | 06:32 | Scanned the full actions.log for FAIL entries: fixed 'open a wikipedia page on X' (was trying to open an app) → now opens the Wikipedia page; verified the refusal→local-search fix catches the other two ("I can't browse", financial-advice deflection) | All logged FAILs addressed |

---

## Evening session — Aug 30 (~20:35–21:00 local) — punch-list + typing mode

You left an 8-item list and said "continue working on all features, I'll be back in an hr." All 8 addressed.

| Start | End | What I did | Result |
|---|---|---|---|
| 20:35 | 20:45 | #5 **Grant-Permissions flow**: new `permissions.py` (Accessibility via AXIsProcessTrustedWithOptions + Automation via a benign System-Events call), a "🔓 Grant Permissions" menu item, and a startup nudge — opens the exact Settings pane so you toggle Sheru on once, like any other app | Live; menu item + nudge |
| 20:35 | 20:48 | #3 **Menu-bar icon** was missing (template=True on a colored PNG rendered near-invisible) → switched to the 🦁 emoji title | Icon visible in menu bar |
| 20:45 | 20:56 | #6 **Hands-free typing/dictation mode**: two Tier-0 router rules ("open <person>'s chat and activate typing mode" → opens their WhatsApp chat; bare "activate typing mode" → types into whatever's focused). While on, every spoken line is typed via System Events, with Return-to-send ONLY in chat apps (WhatsApp/Messages/Telegram/Discord/Slack/Signal) so dictating into a document never auto-sends. "disable/stop/exit typing mode" leaves it | Routing + intercept verified; gated on Accessibility grant |
| 20:56 | 20:57 | #4 **Hold-F5 → chat** felt slow: Karabiner hold threshold 350ms → **220ms** (−37%) | Auto-reloaded by Karabiner |
| 20:57 | 20:58 | Restarted Sheru.app (single-instance) on the new code; verified one instance, models warm 7.0s, socket + F5 hotkey up | App healthy |
| 20:58 | 21:00 | Safe end-to-end check of the typing keystroke into TextEdit (sanctioned scratch target) → **confirmed it blocks until Accessibility is granted to Sheru.app** — which is exactly what the #5 flow is for. Cleaned up TextEdit (no save). Kicked off the deferred #6 research (text-box recognition / mouseless clicking) as a background agent → `docs/RESEARCH-mouseless-typing.md` | Mechanism validated |
| 21:00 | 21:15 | Caught + fixed a real bug in typing mode: entering it by voice (and each dictated line) returned *before* the follow-up-arming code, so the mic closed right after "say what you want to send" — hands-free typing was dead on arrival. Now each typing path re-opens the mic (20s), a quiet window exits typing mode cleanly (not "Anything else?"), and I audited every reply path so continued conversation holds consistently. Added routing/disable regression checks | Fixed + tests pass |
| 21:15 | 21:22 | Hardened typing mode: gate entry on the app's own `AXIsProcessTrusted` (so it guides you to Settings instead of the ~2-min hang an ungranted keystroke causes), and put timeouts on the keystroke calls so a mid-session grant-revoke drops out cleanly with a spoken notice | No more freeze risk |
| 21:22 | 21:28 | Deferred #6 research **landed** → `docs/RESEARCH-mouseless-typing.md` (469 lines, API constants verified vs pyobjc 12.2.2). Top finding: for reliable WhatsApp send + real text-box control, add a small Accessibility layer (`src/sheru/ax.py`) — enable Electron's AX tree, find the composer, `AXPress` the Send button (no blind sleep+Return), and enumerate pressable elements for voice "click X". Ends with a 5-step build order. **Left unbuilt on purpose** — you framed it as "research later", and it needs Accessibility granted to test | Doc ready; build is your call |

**Already done earlier this session** (from your list): #1 continued conversations (flag-based follow-up arming + an "anything else?" check-in before closing), #2 the duplicate Sheru.app removed, #7 Devanagari no longer reaches TTS (Roman-Hinglish replies + romanize), #8 the orb turns blue for Claude (CoreAnimation state flip moved onto the main thread).

### ⚠️ One thing needs YOU (30 seconds)
Typing mode, the F5 hotkey, and WhatsApp call/automation all need **Accessibility** (and Automation) granted to **Sheru.app** — a fresh grant because the packaged app is a different identity from the terminal. Click the menu-bar 🦁 → **🔓 Grant Permissions**, then toggle **Sheru** on under Accessibility (and allow the Automation prompts). Until then those features silently do nothing. Everything else works without it.

---

## Late session — Aug 30 night → Aug 31 (~21:00–02:45) — Shortcuts, menu bar, auto-start, fine-tune

You asked me to keep going after the punch list: research Shortcuts, fix a few things you hit, make the menu-bar
icon good + persistent + auto-starting, and retry the fine-tune. All done. Sheru is **up on the base model** with the
**✦ sparkles** menu-bar icon, auto-starting at login.

| Start | End | What I did | Result |
|---|---|---|---|
| 21:00 | 21:30 | **Shortcuts integration** (from the link you shared): inventoried macOS Shortcuts, and queued a build spec — a `run_shortcut` bridge (Sheru borrows ANY Shortcuts action), then Set Focus/DND by voice, window management, on-device OCR, and proactive automations. Native "Hey Sheru" wake word (Vocal Shortcuts → Siri, or Voice Control) documented as a deferred future item | Spec in `docs/SHORTCUTS-INTEGRATION.md` |
| 21:30 | 22:15 | **Fixed the volume "%" bug** you hit: "set volume to 20%" was escalating to the LLM, which just *said* "done" without acting — the grammar only matched "percent" spelled out, not "%". Now normalizes % → percent + a new "increase/reduce by N%" rule. All volume commands stay tier-0 deterministic | Fixed + regression tests |
| 22:15 | 22:30 | **Mic locked to the built-in MacBook mic** over your headset (the headset picks up room noise and garbles STT). Logs the chosen device so it's verifiable | Built-in enforced |
| 22:30 | 00:40 | **Menu-bar icon**: you disliked the 🦁 emoji and it kept vanishing. Root-caused two bugs — a 2-second alarm timer set the title to `None` (wiped it), and deeper, `/Applications/Sheru.app` runs a python *outside* its bundle so macOS treats the process as faceless and collapses the status item to zero height. Showed you white shape-only **SF Symbol** options; you picked **✦ sparkles** (native, theme-adapting) | Sparkles chosen, config-driven |
| 00:40 | 01:20 | **Durable auto-start**: installed a **LaunchAgent** that runs Sheru in your GUI session → the sparkles icon shows, it **auto-starts at login, survives restarts, and restarts on a crash** (honoring a clean Quit). Reproducible: `packaging/com.sheru.assistant.plist` + `install-autostart.sh` | Sparkles persists + auto-starts |
| 01:20 | 02:45 | **Fine-tune retry** (your ask): distilled **150 real utterances via Claude** + a 278-example seed → **397 train / 44 valid** (bigger + more diverse than last night); made the eval-gate **honest** (excludes the held-out battery from training so an overfit adapter can't cheat); trained a LoRA on the **2507 base** (gentle LR 5e-5, checkpoints every 50); eval-gated base vs every checkpoint | **KEPT BASE** — see below |

### Fine-tune result — KEPT BASE (the eval-gate did its job)
| Model | Overall (held-out battery) | Chat-neg (must stay clean) |
|---|---|---|
| **BASE (Qwen3-4B-Instruct-2507)** | **32/38 (84%)** ✅ deployed | 6/6 |
| LoRA ckpt 50 / 100 / final | 6/38 (collapsed) | 6/6 |
| LoRA ckpt 200 (best adapter) | 29/38 | 6/6 |

The LoRA overfits the narrow router task almost instantly (val loss → 0.03 by iter 50) and then **generalizes terribly
to the held-out battery** — most checkpoints collapse to outputting no tool call at all. Every adapter scored **below**
base, so I kept base (`config.LOCAL_ADAPTER = None`). This is the same, correct outcome as last night: the base 2507 is
already strong, and fine-tuning a small narrow-task dataset doesn't beat it. **The durable win tonight is the honest,
bigger dataset + gated pipeline** (`data/finetune/`, gitignored) for future attempts — not a winning adapter. To actually
beat base would likely need a much larger, more diverse corpus (thousands of real labeled utterances) or a different
target than tool-call memorization.

### ⚠️ Needs YOU (30 seconds) — permissions moved
Sheru now runs as a **login agent** (a fresh macOS permission identity, not the old `.app`). So re-grant, once:
**Accessibility** + **Automation** (F5 hotkey, typing mode, WhatsApp auto-send) and **Microphone** (first F5 will prompt) —
via the menu-bar **✦ → 🔓 Grant Permissions**, or just approve the macOS prompts. Leave the "background item" enabled in
System Settings → Login Items. Everything else works without it.

---

## Overnight #2 — Aug 31 (~02:00–03:05) — Shortcuts integration + real-usage fixes

After the fine-tune (kept base), you said "continue working" + rebooted for a clean slate. I built the queued
Shortcuts integration and fixed real misroutes from your usage log. **Sheru is live (LaunchAgent) with all of it.**

| Start | End | What I did | Result |
|---|---|---|---|
| 02:05 | 02:20 | **`run_shortcut` bridge** (`actions/shortcuts.py` + grammar): say **"run shortcut &lt;name&gt;"** and Sheru runs it (fuzzy-matched to your shortcut list, timeout-guarded, graceful if unknown). This is the leverage point — Sheru can now borrow ANY Shortcuts action | Shipped + tested |
| 02:20 | 02:45 | **Focus / DND by voice**: "turn on do not disturb", "set focus to work", "turn off focus", "what's my focus" → Focus helper shortcuts. Focus has no clean scripting API, so Shortcuts is the way | Shipped + tested |
| 02:45 | 03:00 | Scanned your **actions.log** for real FAILs → fixed two: **"how do you feel about me"** was being treated as a "how-to tutorial" (howto rule caught "how do you…"); and **brightness** ("maximize the screen brightness", "set brightness to 50", "dim the screen") hit the LLM's "I can't" → now routes to a "Sheru Set Brightness" helper Shortcut | 2 real bugs fixed |
| 03:00 | 03:05 | Restarted Sheru on the new code; verified run_shortcut / brightness / howto routing live; sparkles icon up | Live |

### ⚙️ To turn the voice commands on, create these Shortcuts once (I can't make them from the CLI)
In the **Shortcuts app**, name each exactly — full steps in `docs/SHORTCUTS-INTEGRATION.md`:
- **`Sheru Set Focus`** (Set Focus → On, focus = Shortcut Input) · **`Sheru Focus Off`** (Set Focus → Turn Off)
- **`Sheru Get Focus`** (Get Current Focus → output name) · **`Sheru Set Brightness`** (Set Brightness = Shortcut Input)

Until then, Sheru tells you exactly which shortcut to create instead of failing. And **run any shortcut you already
have** with "run shortcut &lt;name&gt;" — no setup needed. (Bluetooth toggle skipped — it's not a Shortcuts action and
needs a CLI I won't install unprompted.)

**03:05–03:50 — hardening + cleanup.** Ran an adversarial code review over tonight's changes; it found and I fixed 5
real bugs: (1) "what's my focus" always said "not in any focus" — the shortcut CLI's `-o -` output flag was wrongly
tied to `-i -`, so input-less query shortcuts never returned anything (now always captures output); (2) a loose
shortcut-name match could fire the WRONG (possibly destructive) shortcut unconfirmed → tightened to exact/near-exact
only; (3) "stop do not disturb"/"stop focus" were swallowed by the generic "stop" rule → added a lookahead; (4) the
volume/brightness preprocessing could rewrite number-words inside a message body ("…needs thirty chairs" → "30") →
now skips messaging commands; (5) brightness now clamps 0–100. All regression-tested. **Also cleaned up test
side-effects** (I'd been running real `route()` calls that played Spotify + opened YouTube videos in Brave — paused
Spotify, quit Brave; captured the lesson so it stops). Sheru restarted on the fixed code, healthy.

**03:50–04:15 — window management by voice (via Rectangle).** "maximize this window", "make it full screen",
"left/right/top/bottom half", "move window left", "center this window" → Rectangle's URL scheme. Rectangle was
already installed; I enabled its URL scheme so this works with **no setup** (unlike Focus/brightness, which need
you to create helper shortcuts). Grammar is keyword-anchored so it never false-fires. Restarted Sheru. **All three
queued Shortcuts items are now built** (run-shortcut bridge · Focus/DND · window management) plus brightness.
Deliberately left for later (both need setup I can't do or safely test at night): **OCR** ("read this screen" via a
Extract-Text-from-Image shortcut) and **proactive automations** (battery/time/app triggers). Say the word when
you're up and I'll wire those too.

**04:20–05:00 — reliability audit + fixes.** Ran a deep adversarial audit of the routing / voice-loop / escalation
paths (the "conversation dropped / misrouted" complaints). It confirmed escalation/failure handling is solid but
found real bugs — fixed 6: (1) greedy weather/news rules swallowed "remind me to check the weather" and "text mom
the weather looks bad" → messaging/reminders now fall through; (2) **any handler crash silently killed the voice
loop** (mic just closed) → now caught, speaks a brief error, loop survives — this likely explains most "it just
stopped" moments; (3) a pending message draft folded the next unrelated command into itself ("actually play music"
re-drafted) and a stale draft hijacked the first command after a restart → added a new-intent escape; (4) a Claude
answer with no stream deltas could "succeed" silently → now speaks the final answer; (5) local-LLM actions logged
`tool=None` and could re-open the mic after a fire-and-forget action (echo risk) → fixed; (6) "stop it"/"stop that"
now cancel an in-flight Claude turn. All regression-tested, Sheru restarted. **Left for you (low, needs judgement):**
a resolved-song turn doesn't re-open the mic for a follow-up (minor); pressing F5 mid-Claude-turn can orphan the
old `claude -p` process (uncommon).
