# Sheru — Manual Test Checklist

Human-in-the-loop tests for the parts the automated harness (`tests/stress_test.py`) can't cover: real mic,
GUI, F5, and side-effecting actions. Mark ✅/❌ and note what happened. Start Sheru: `uv run sheru` (or open
`Sheru.app`). Automated routing coverage is separate — run `uv run python tests/stress_test.py`.

## A. Activation & voice loop
- [ ] Press **F5** (physical mic key) → glassy panel opens showing **"Listening…"**.
- [ ] Say **"what time is it"** → hears you, replies out loud + shows text, footer shows **⚡ Sheru (local)**.
- [ ] Press **F5 again** (panel still open) → it listens again (follow-up works).
- [ ] Click the **🎙 button** in the panel → listens again.
- [ ] Say nothing after F5 → after ~8 s shows **"didn't catch anything"** (no hang).
- [ ] Speak quietly / far from mic → does it still catch? (tune `SHERU_MIC_GAIN` if not)
- [ ] F5 from *inside another app* (browser focused) → still activates (global monitor).

## B. Type-to-Sheru panel
- [ ] Panel looks glassy/frosted, rounded, readable in light & dark.
- [ ] Type "what time is it" + Enter → answers silently in the panel (no speech).
- [ ] **Esc** hides the panel.
- [ ] Type a Claude task ("summarize the news about the m5 macbook") → footer shows **☁️ Claude · Ns** ticking.

## C. Real app actions (side effects — watch what happens)
- [ ] "open spotify" → Spotify opens. "quit spotify" → it quits.
- [ ] "switch to obsidian" → Obsidian comes forward.
- [ ] "open the zen browser" → Zen opens. "switch to college profile" → Zen opens your college profile.
- [ ] "use google" then "search for best momos" → opens a **Google** search (not DuckDuckGo).
- [ ] "show me pictures of tigers" → image results open.
- [ ] "volume 30" / "turn it up" / "mute" → system volume changes.
- [ ] "pause" / "next song" → controls Spotify/Music playback.
- [ ] "set a timer for 1 minute" → after a minute it says the timer is done.

## D. Music (Spotify)
- [ ] "play choo lo" → does it play the actual song, or open Spotify search? (direct play needs Spotify API creds)
- [ ] "play music" → resumes playback (not a search).

## E. Messages (irreversible — use a test contact)
- [ ] "message <test-contact> that I'm running late" → Sheru **drafts** a message and asks to confirm/rephrase.
- [ ] Say "make it shorter" → it rephrases and re-asks.
- [ ] Say "send it" → sends via Messages (or opens it pre-filled to press return). **Verify the recipient + text.**
- [ ] Start another, say "no cancel" → nothing is sent.

## F. Memory (persists across restarts)
- [ ] "remember I prefer tea over coffee" → "Got it…".
- [ ] "what do I like to drink" → answers **tea**.
- [ ] Quit and relaunch Sheru → "what do I like to drink" still answers tea (memory.jsonl persisted).

## G. Current info → Claude
- [ ] "what's the weather" → "Let me check" then a real spoken weather summary for **Ravangla** (not "I can't").
- [ ] "search for X and summarize" → Claude searches + summarizes out loud.
- [ ] Turn off Wi-Fi → "what's the weather" → falls back to a local answer (no hang; ~150 s cap).

## H. Onboarding / setup
- [ ] Menu → **Setup / Permissions…** → onboarding window shows all permissions ✅ (Grant buttons hidden).
- [ ] Location field shows **Ravangla, Sikkim**; changing + Save updates it.

## I. Data capture (dev mode)
- [ ] After a few voice commands: `data/recordings/` has WAV clips; `data/recordings.jsonl` pairs each with its
      transcription; `data/journal.jsonl` logs every input + routing + latency.

## J. Robustness / edge
- [ ] Rapid-fire: F5 → speak, immediately F5 → speak again → no crash, both handled.
- [ ] Gibberish / mumbling → doesn't do something destructive; routes to chat or "didn't catch".
- [ ] "open <app that isn't installed>" → says it couldn't find it (no crash).
- [ ] Multi-intent "open spotify and play choo lo" → note what it does (known limitation: single-intent).

## Known limitations to confirm, not fix
- Mic indicator (orange dot) shows while listening — unavoidable for any third-party app (Apple-only always-on).
- Play-specific-song is search-only until Spotify API creds or the sheru-vision native-control lands.
- Multi-app / multi-step tasks route to one action; complex ones should go to Claude.
