# Sheru — The Journey

*The story of building Sheru: a local-first, JARVIS-like voice assistant on a MacBook Air M5.
Kept as a running history so that when Sheru is finally "the ultimate personal assistant,"
we'll have the record of its birth — the experiments, the dead ends, the fixes, and the wins.*

**Owner:** Yash Gupta · **Machine:** MacBook Air M5, 16 GB, macOS Tahoe · **Stack:** Python 3.12 (uv), MLX,
pyobjc/AppKit, `claude -p`. Apache-2.0.

---

## The vision

One assistant, always a keypress away, that: opens apps and controls the Mac, answers questions, plays music
and videos, messages and calls people, sets alarms — and does **~90–95% of it ON-DEVICE**, escalating to Claude
only when a task genuinely needs it. The north star from day one: *"using just Claude for everything is cheating.
We should be on even ground of computation power."* Local-first isn't a nice-to-have; it's the whole point.

---

## Chapter 0 — Architecture (2026-08-28)

The founding decision was a **tiered router** — route before acting, escalate only when needed:

```
mic → VAD → wake/PTT → STT ─┐
                            ▼
  Tier 0  regex grammar (no LLM)     "open X", "play X", "timer", math   10–200 ms
  Tier 1  local LLM tool-calling     Qwen3-4B via mlx-lm, Hermes JSON     0.3–0.8 s
  Tier 2  Claude Code (headless)     coding / files / multi-step / hard   3 s+ streams
```

Decisions made (and mostly still standing): Python core packaged as a signed `.app`; **local MLX model, no
Anthropic API key**; English + (later) Hindi; deterministic control + browser automation for v1, vision/a11y
deferred. Cost target: **$0/month** — the subscription quota is the only budget.

**Lesson that shaped everything:** most daily commands should never reach the LLM. A wide Tier-0 grammar is what
makes a small local model viable.

---

## Chapter 1 — "The dumbness was plumbing, not the model" (2026-08-28 → 29)

The first real runs felt dumb — weather/news/summarize came back as *"I'm processing…"* (hallucination). The
root causes were almost never the model:

- **★ Claude escalation was org-blocked.** A GUI/login-item launch inherits no `CLAUDE_CONFIG_DIR`, so `claude -p`
  used the default `~/.claude` — an empty org with Claude Code disabled. Every escalation silently failed →
  dumb local fallback. Fix: pin `CLAUDE_CONFIG_DIR=~/.claude-ashish` (the real login).
- **★ Hindi needs Whisper.** parakeet-tdt (the fast STT) is English/European only and heard Hindi as Russian
  ("Play Lori" → "Плелори") — the real cause of wrong songs/names. Added `mlx-whisper` large-v3-turbo,
  auto-detecting Hindi/English/Hinglish.
- **Network gotcha:** on college wifi a Sophos firewall does TLS interception, breaking `claude -p` and HTTPS
  APIs from Python (but not the browser). Sheru degrades to local; models are pre-downloaded + `HF_HUB_OFFLINE`.

**Lesson:** when an AI system looks stupid, suspect the plumbing (auth, STT, network) before the weights.

---

## Chapter 2 — The model journey: 8B → 4B → 4B-Instruct-2507

- Started aiming for **Qwen3-8B** for quality.
- **Switched to 4B** when the 8B-4bit (~4.6 GB) + Whisper + Kokoro TTS pushed the 16 GB machine into swap and
  froze it. A head-to-head probe showed **4B and 8B route tools *identically*** — 8B was only slightly warmer in
  chit-chat at ~1.7× latency and ~2× RAM. Stability won.
- **Upgraded to Qwen3-4B-Instruct-2507** (2026-08-30), eval-gated: on the held-out routing battery it beat the
  base 4B **84% vs 79%** with no chat-negative regression, at the *same* footprint. The "best of both worlds"
  wasn't a bigger model — it was a better-tuned 4B.

**Lesson:** on a 16 GB machine, the right model is the one that leaves room for the STT + TTS + OS. And a newer
same-size checkpoint can beat a bigger old one where it matters (tool-calling).

---

## Chapter 3 — The local-first push (make the 90–95% real)

The success criterion demanded that current-info and everyday queries stay on-device. Built a **layered,
escalate-last** pipeline for any live query:

1. **Exact structured answerers** (`actions/structured.py`) — keyless, no LLM:
   - **FX** via Frankfurter (ECB): "100 dollars in rupees" → exact converted amount.
   - **Weather** via Open-Meteo + the IP-geolocated location: temp + condition + today's range.
   - **News** via Google News RSS: top headlines, or a topic search.
   - **Wikipedia** summary for "who/what is X".
2. **DuckDuckGo scrape + local summarize** (`search_local.py`, HTML→lite fallback so a blocked endpoint doesn't
   force an escalation).
3. **Claude** — only for real coding/files/multi-step.

Plus: a **safe AST calculator** (exact math, continued calculations, word-numbers), the **macOS Dictionary**
(`DCSCopyTextDefinition` — the trackpad "Look Up", fully offline) for "define X", and a rule forcing *changing*
stats (population/GDP/net worth) to local search instead of the model's stale memory.

**Result:** verified that 6/6 real escalations from the usage log now resolve on-device — including a stock
price via scrape+summarize.

**Lesson:** the local model should only handle what it *can* know (routing, static facts, chit-chat). Live and
changing data belongs to exact APIs or search — never to a frozen 4B guessing.

---

## Chapter 4 — The overnight autonomous session (2026-08-30)

Ran unattended overnight with a heartbeat. Highlights:

- **Fine-tuning, done right and rejected.** Trained a LoRA on the 4B (mlx_lm.lora), then **eval-gated** it on
  novel/broken-English utterances. It *lost* — the tiny synthetic dataset overfit (train loss ~0.01 by iter 80);
  the adapter regressed chat-negatives and even hallucinated a `create_folder` tool. **Kept the base model.**
  This is the system working as designed: never blind-deploy a fine-tune. (`docs/FINETUNE-RESULT.md`.)
- **~16 routing/parsing bugs fixed**, most found by a code-audit agent and by stress-testing in broken English:
  calc hijacking "volume 20 percent", spoken **number-words** ("five plus five"), alarm/reminder parsing
  ("7 in the morning", "half an hour", "quarter past 7"), reminders keeping context, and more.
- **Everything eval- or test-gated**; a 40-check regression suite (`tests/test_overnight_fixes.py`) locks the
  fixes in — and mocks every side effect so it never rings a phone or plays a song.

**Lesson:** an autonomous agent needs *gates* — an eval battery, a regression suite, and a rule to keep the base
when the experiment doesn't beat it. Confidence comes from the gate, not the model.

---

## Chapter 5 — The GUI becomes a product (2026-08-30)

A flat text panel became an **iMessage-style bubble chat**, designed with Yash choice-by-choice:
- Your turns as warm **amber→orange gradient** bubbles (Sheru means *lion*); Sheru's as tinted bubbles that show
  *where the work happened* — **gold + ⚡ = on-device, blue + ☁️ = Claude** — making the local-first ratio
  visible at a glance.
- Comfortable spacing, per-turn timestamps, typing dots + elapsed time, a clean SF-Symbol mic that glows gold
  when listening, and an idle-**breathing** orb that stays present through the whole exchange.
- A **history browser** (menu bar *and* a clock button in the panel): time-gap "sessions", search, ★-to-keep,
  and **7-day retention** unless starred.

**Tooling win:** built `scripts/preview_panel.py` — a standalone harness that renders the panel with sample
turns, so the GUI could be **screenshotted and iterated** without launching the whole app. Every GUI change was
verified by capturing the panel and reading the image.

**Lesson:** you can't design a native UI blind. A screenshot loop turned GUI work from guessing into iterating.

---

## Chapter 6 — Real capabilities, real edge cases

Each of these was a small journey of its own:

- **WhatsApp calling (confirm-first).** No call URL scheme on Mac — so Sheru opens the chat and drives WhatsApp's
  own **Call ▸ Voice/Video Call menu item**. First attempt failed: the Call menu only exposes "Voice Call" *after*
  the chat loads, and a fixed 1.3 s wait was too short → now it **polls** for the enabled item. Never auto-dials:
  a Call/Cancel card gates every call. (And I declined to autonomously call/message real people to "test" it —
  that's the user's live tap.)
- **Spotify playlists without a login.** AppleScript plays a playlist URI directly (`play track
  "spotify:playlist:…"`), so no OAuth — the only gap was finding the URI by name, solved by **learning the link
  once** ("my bhajan playlist is …", TV-channel style). Bug fixed along the way: the router lowercases everything,
  but Spotify IDs are case-sensitive → pull the link from the original text.
- **YouTube tutorials.** "how to play raag yaman on flute" was opening a random Short — because the scraper took
  the *first* videoId (usually an ad/reel). Fixed to target a real search result (`videoRenderer`) → the actual
  flute lesson. And "how to X" now routes to a tutorial, never to play-song.

**Lesson:** the last mile of every feature is an edge case — menu timing, URL case-sensitivity, the wrong DOM
node. Ship the happy path, then chase the one that bit you.

---

## Chapter 7 — Voice that doesn't break

- **"Speaks Russian all of a sudden."** The English Kokoro voice can't pronounce **Devanagari** and garbles it.
  Fix, two-pronged: tell the model to reply in **Roman Hinglish** (not Devanagari), *and* romanize any stray
  Devanagari before TTS (`गाना बजाओ` → `gana bajao`). Separately, names like "Satya" triggered phonemizer
  **language-switch flags** that Kokoro vocalized as gibberish — patched the backend to `remove-flags`.
- **Continued conversation that actually continues.** The follow-up window was set when the reply was *generated*,
  so a long reply ate the whole window before Sheru even stopped talking. Fixed to arm the window *after*
  speaking, made it generous (20–25 s), added a soft "your turn" tone (eyes-free), and let you end with
  "no" / "that's all" / "thanks".
- **The orb never turned blue.** `_start_progress` ran on the background voice thread, but CoreAnimation must run
  on the main thread — so the color change was silently dropped. Routed through the main thread.
- **"Crashed / can't restart."** No single-instance guard — a background instance and an app-shortcut launch
  fought over the mic + hotkey. Added a guard: launching again just activates the running one.

**Lesson:** voice UX lives and dies on timing and threads. Most "it's broken" reports here were a race, a wrong
thread, or a window measured from the wrong moment.

---

## Where it stands

- **Local-first:** currency, weather, news, definitions, "who/what is X", math, and changing stats answer
  on-device; coding/files/multi-step go to Claude — with the orb/badge showing which.
- **Model:** Qwen3-4B-Instruct-2507-4bit, 84% routing on the eval battery, ~2.5 GB, snappy.
- **Voice:** Whisper STT (Hindi/English/Hinglish), Kokoro TTS (Roman-Hinglish-safe), follow-up conversation that
  holds, an always-present orb.
- **GUI:** bubble chat with the local/Claude signal, history browser, message/call confirm cards.
- **Capabilities:** apps, volume, timers/alarms/reminders, messages, **WhatsApp calling**, Spotify songs +
  **playlists**, YouTube videos + **tutorials**, web search + summarize, the generative-agent (Claude writes →
  scratchpad → offer to run).
- **Discipline:** eval-gated model + fine-tune decisions, a regression suite, honest logs.

## Guiding lessons (the ones we keep relearning)
1. When it looks dumb, suspect the plumbing — not the weights.
2. Keep the heavy model out of the loop; a wide grammar + exact APIs + search do the work.
3. The right model is the one that fits *with* the STT and TTS, not the biggest one.
4. Gate every experiment (eval battery, regression suite); keep the base when it doesn't win.
5. You can't build a UI or a voice loop blind — screenshot it, log it, time it from the right moment.
6. The last mile of a feature is always an edge case. Chase the one that bit you.

*— continued as the journey continues.*
