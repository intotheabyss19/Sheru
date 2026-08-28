# Overnight pass — 2026-08-29 (branch `overnight`)

You asked me to stress-test and improve Sheru while you slept, and to read where it actually disappointed.
I did. **The dumbness was almost entirely plumbing, not the model.** Below is what was broken, what I fixed
and verified, and the few things that need your call. Everything is committed on branch `overnight` (5 commits
on top of the baseline), so `git diff main` shows the whole night.

## TL;DR — do this when you wake
1. **Restart Sheru** to pick up the fixes: `pkill -f .venv/bin/sheru; (cd ~/Projects/Sheru && .venv/bin/sheru &)`
2. **Try Hindi** (the big one): `SHERU_STT=whisper` before launch, or add `"stt_backend": "whisper"` to `data/profile.json`, then say a Hindi song. Parakeet literally can't do Hindi; Whisper can (proof below).
3. Skim §2 (the Claude fix — that alone fixes most of the "I can't browse" dumbness) and §5 (model: **you don't need 9B**).
4. Merge if happy: `git checkout main && git merge overnight`.

---

## 1. What was actually making it feel dumb (root causes, ranked)
From your real `data/journal.jsonl` (102 turns) + `data/sheru.log`:

1. **Claude escalation was silently BROKEN.** The log had: `claude -p failed (Your organization has disabled
   Claude subscription access for Claude Code)`. Every weather/news/search/screen/bash request that hands off
   to Claude *failed* and fell back to the dumb local 4B, which then refused with "I can't browse." → §2.
2. **Hindi speech was mangled by STT.** Parakeet-v3 is English/European only. "Sunya song by Kalashkir" became
   *"Sienna by The Marías"*; real Hindi came out as garbage. → §4.
3. **No memory across turns.** History was only recorded on the Tier-1 (local-LLM) path, and Claude never
   resumed its session — so follow-ups ("who sings this?", "what about tomorrow?", "search the web for that")
   had zero context. → §3.
4. **Missing basics it just guessed at:** "make a folder" → *"Opening Finder"*; "open your trainer" →
   *"Opening Finder"*; refused simple facts ("when did India get independence" → "I can't browse"). → §3/§6.

---

## 2. ★ The big fix: Claude escalation repaired
Your real Claude Code login is `~/.claude-ashish` (the `claudea` command sets `CLAUDE_CONFIG_DIR`). The default
`~/.claude` is your empty/DataAnnotation setup, whose **org has Claude Code disabled**. When Sheru launches from
the menu bar / login item it does **not** inherit `CLAUDE_CONFIG_DIR`, so `claude -p` used the wrong account and
every escalation died.

**Fix:** Sheru now pins `config.CLAUDE_CONFIG_DIR` → `~/.claude-ashish` for both headless `claude -p` and the
interactive trainer window (override with `SHERU_CLAUDE_CONFIG_DIR` or profile `claude_config_dir`).
**Verified:** `claude -p` with that config dir returns a real answer ("pong"). This single fix un-breaks
weather, news, search, screen and "ask Claude" — the bulk of the "I can't browse" dumbness.

## 3. Continued conversation — fixed & tested
- Every exchange (Tier 0/1/2) is now recorded in `router.history`, not just local-LLM turns.
- Claude **resumes** the same session for a follow-up within 120s; a fresh thread gets the last few turns
  injected so "it"/"that"/"there" resolve.
- Mic stays open longer after a spoken answer, and the push-to-talk loop waits out an in-flight Claude turn so
  voice follow-ups actually continue the thread.
- A one-off song lookup no longer hijacks the conversation's Claude session.
- **New test:** `tests/conversation_test.py` — 12 checks, all pass (history, resume, context injection).

## 4. ★ Hindi — the biggest remaining lever (ready, one flip to enable)
Added a **Whisper** STT backend (`mlx-whisper`, already installed; model downloaded). Same audio, both engines:

| You say | Parakeet (current default) | Whisper (new) |
|---|---|---|
| play tum hi ho by arijit singh | `Playtum Hiho by Arajet Sinnh` | `Play Tum Hi Ho by Arjeet Sinr` |
| तुम ही हो गाना बजाओ अरिजीत सिंह का | `Tunghi Hugana Bajao Arejit Singhka` | `तुम ही हो गाना बजाओ अरजीत सिंग का` |
| मम्मी को मैसेज करो कि मैं लेट आऊंगा | `Mamiku message karuki mek radko...` | `ममी को मैसेज करो कि मैं रात को...` |

**Enable:** `SHERU_STT=whisper` (env) or `"stt_backend": "whisper"` in `data/profile.json`.
**Why not default already:** I only tested TTS-generated audio, not your real noisy mic, and Whisper can
hallucinate text on silence. Flip it, talk to it in Hindi for a day; if it holds up we make it the default.
Note: your routing already handles Hindi — the 4B correctly routed "mummy ko message karo" → draft_message and
"das minute ka timer laga do" → set_timer. **STT was the whole problem, not the model.**

## 5. ★ Model: you do NOT need Qwen3.5-9B
I downloaded Qwen3-8B-4bit and probed 4B vs 8B on the same 10 commands (tool-routing):
- **Identical routing on every tool case** (open, play, Hindi message, Hindi timer, escalate-to-Claude).
- 8B only wins on chit-chat *warmth* (told an actual joke; clean "36") — at **~1.7× latency** (2822ms vs 1649ms
  per decision) and **~2× RAM**.
- Qwen3.5-9B is real (`mlx-community/Qwen3.5-9B-MLX-4bit`) but (a) may be a vision model needing `mlx-vlm` not
  `mlx-lm` — verify before wiring, and (b) ~6GB resident sits at the 16GB edge, swaps with a browser open.

**Recommendation:** stay on **4B** (default) — it routes as well as 8B and is snappier. It's already set to read
`profile.json` `llm_model`, so if you want warmer chat, add `"llm_model": "mlx-community/Qwen3-8B-4bit"`
(downloaded, ready). **Skip 9B** — no benefit for basic agentic use, real RAM risk. The money/RAM you'd spend on
a bigger model buys nothing here; the fixes above are what mattered.

## 6. The disappointments, itemized (from your logs) → what I did
| Real utterance (journal) | Was | Now |
|---|---|---|
| "when did India get independence?" | "I can't browse the internet" | answers **1947** (verified) |
| "closing price of SBI today?" | "I can't browse" | **escalates to Claude** (verified) |
| "make a new folder … called Yesh" | "Opening Finder" | **creates the folder** (verified) — `actions/files.py`, sandboxed to home |
| "create a .txt file here called hello.txt" | "Opening Finder" | **creates the file** |
| "open a terminal in projects" | wrong | opens Ghostty cd'd there |
| "open your trainer" / "start a new cloud session" | "Opening Finder" | **triggers the trainer** |
| "search the web for that" | opened a literal tab for "the web for that" | summarizes the last topic |
| weather | handed to Claude (which was failing) | **silent wttr.in fetch** — "It's 20 degrees in Gangtok, light rain" (verified, no Claude needed) |
| local model on hard/unknown | guessed or refused | **escalate-don't-guess** prompt: answer only simple facts, else ask_claude, never "I can't browse" |

## 7. Voice
- **Fixed the wobble:** the `pitchMultiplier = 1.22` on a *compact* voice was the warble. Set pitch → **1.0**;
  preference order now favors installed **enhanced** males (Rishi = Indian English, then Daniel, Fred).
- **Bigger upgrade (optional):** Kokoro-82M via `mlx-audio` (voice `am_michael`, Apache-2.0, ~90ms, ~900MB) is
  far smoother than AVSpeech. Not wired yet — it's a new dep + one reported NaN bug to validate. Say the word.
- **Kid voice:** no off-the-shelf child voice exists in any local engine. The clean path is Kokoro + a
  `parselmouth`/Praat post-process shifting pitch **and formants together** (+3–5 semitones, formants ×1.1–1.2).
  Cosmetic; parked until you want it. (Siri voices can't be used from AVSpeech — Apple locks them.)

## 8. Background / no focus-stealing (Siri-style)
- **Done:** web search / images / URLs now open with `open -g` (background, no focus theft). Spotify already did.
- **Free system win (you run once):** stop macOS yanking you to another Space —
  `defaults write com.apple.dock AppleSpacesSwitchOnActivate -bool false && killall Dock`
- **Dedicated Space:** right-click each helper app (Zen, WhatsApp, Spotify) in the Dock → Options → Assign To →
  Desktop N. No reliable *scriptable* Spaces API exists on Tahoe (yabai's is broken there; AeroSpace is the
  no-SIP option if you want programmatic placement later).
- **WhatsApp is the stubborn one:** sending via a synthetic Return *requires* the window frontmost. Truly silent
  send needs background WhatsApp-Web DOM automation or an Accessibility `AXPress` on Send — a real build; flagged
  for later.

## 9. What I did NOT change (needs your call)
- Making Whisper / 8B the **default** (validate on real input first).
- Kokoro voice engine (new dep) and the kid-voice DSP.
- The `AppleSpacesSwitchOnActivate` system tweak (I don't change your OS settings unasked).
- Background WhatsApp-Web sending, and screen-reading (Claude headless can't see the screen — separate build).
- I did **not** restart the running app or push anything.

## 10. Verification log
- `claude -p` with `~/.claude-ashish` → real answer ✓
- `tests/conversation_test.py` → 12/12 ✓
- `tests/stress_test.py --no-llm` → English grammar routes green; new routes (trainer/fs/terminal/weather/silent-search) confirmed ✓
- Live 4B: India→1947, SBI→escalate, folder→created, weather→real ✓
- STT: parakeet vs whisper on Hindi audio ✓ (table §4)
- 4B vs 8B routing probe ✓ (§5)

Models downloaded to HF cache (gitignored, not committed): Qwen3-8B-4bit (4.3GB), whisper-large-v3-turbo (1.5GB).
