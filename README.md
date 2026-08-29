# Sheru — hands-free personal assistant for macOS

Wake word **"Hey Sheru"** (say *Sheroo*). Speaks back in a young male voice.
Tiered brain: instant grammar → local Qwen3-8B → Claude Code (your subscription) with a local fallback.

## Platform requirements (read first)

Sheru is built for **macOS on Apple Silicon (M-series)**. It is **not** cross-platform:

- **GUI** (Spotlight-style panel, menu-bar app) uses **pyobjc / AppKit / rumps** — macOS only.
- **Local models** (LLM, speech-to-text, text-to-speech) run on **Apple MLX** — Apple Silicon only.
- **Actions** (open apps, control Spotify/WhatsApp, terminal, screen OCR, spoken replies) use **AppleScript,
  `open`, Apple Vision, AVSpeech** — macOS only.

On **Windows or Linux it will not run as-is** — see [Running on Windows](#running-on-windows-satya-) below.

## Run

```bash
cd ~/Projects/Sheru
uv run sheru --listen        # terminal voice loop (say "hey sheru, ...")
uv run sheru                 # menu-bar app (🦁), mute + quit in the menu
uv run sheru --text "..."    # one command, no mic (testing)
uv run sheru --no-llm        # grammar-only, no local model (fastest to start)
```

First start warms the models (~4 s). Say **"hey sheru"** then your command; after a reply you can
speak a follow-up for ~6 s without the wake word. Say **"stop"** to cancel.

## What it does now (Phase 1)

- **Apps:** "open zen browser", "quit discord", "switch to obsidian"
- **Zen profile:** "switch to work profile"
- **Search:** "use google" / "search for best ramen", then "summarize the results" (Phase 2)
- **Images:** "show me pictures of tigers"
- **System:** "volume 40", "turn it up", "mute", "pause", "next song", "set a timer for five minutes",
  "what time is it", "what's on my clipboard", "go to github.com"
- **Anything harder:** "ask claude to …" or just ask — routes to Claude Code online, local 8B offline.

## Config (env vars)

| Var | Default | Meaning |
|---|---|---|
| `SHERU_LLM` | `mlx-community/Qwen3-8B-4bit` | judgement model (resident) |
| `SHERU_LLM_FAST` | *(unset)* | optional lighter model tried first (e.g. `mlx-community/Qwen3-4B-4bit`) |
| `SHERU_VOICE` | *(auto: best male)* | voice name or identifier |
| `SHERU_PITCH` | `1.22` | 1.0 = normal, higher = younger |
| `SHERU_STT` | `parakeet` | ears: `parakeet`, `whisper`, or `sarvam` (Saaras v3, best Hindi) |
| `SHERU_TTS` | `avspeech` | voice backend: `avspeech`, `kokoro`, or `sarvam` (Hindi) |
| `SARVAM_API_KEY` | *(unset)* | Sarvam key — from a terminal only; for the menu-bar app use `data/profile.json` |
| `SHERU_SARVAM_VOICE` | `shubh` | Bulbul v3 speaker (`ishita` for female) |
| `SHERU_SARVAM_LANG` | `auto` | `auto` picks `hi-IN` for Devanagari, else `en-IN` |
| `SHERU_REPLY_LANG` | `auto` | reply language: `auto` mirrors the user, `hi` pins Hindi, `en` forces English |

**Hindi voice (Sarvam Bulbul v3):** get a key at [dashboard.sarvam.ai](https://dashboard.sarvam.ai), then

```bash
python -c "from sheru import config; config.update_profile('sarvam_api_key','YOUR_KEY'); config.update_profile('tts_backend','sarvam')"
uv run sheru --text "नमस्ते"
```

`data/profile.json` is gitignored and, unlike env vars, is read by the menu-bar/login-item launch too.

**Full Hindi loop** — ears, brain, and voice all have to agree; the voice alone won't translate an English reply:

```bash
uv run python -c "from sheru import config as c; [c.update_profile(k,v) for k,v in
  {'sarvam_api_key':'YOUR_KEY','stt_backend':'sarvam','tts_backend':'sarvam','reply_lang':'hi'}.items()]"
uv run sheru --listen
```

| | | |
|---|---|---|
| ears | `stt_backend=sarvam` | Saaras v3 — parakeet cannot do Hindi at all, whisper only roughly |
| brain | `reply_lang=hi` | appended to the local model's *and* Claude Code's system prompt |
| voice | `tts_backend=sarvam` | Bulbul v3, speaker `shubh` |

Leave `reply_lang` at `auto` to have Sheru answer in whatever language you spoke.

Every Sarvam call is a network round trip (~0.5–1.5 s). Any failure — offline, bad key, rate limit, reply over
2500 chars, clip over 30 s — degrades instead of breaking: TTS falls back to AVSpeech, STT falls back to
whisper. Sheru never goes mute or deaf because the network did.

**Better voice:** System Settings → Accessibility → Spoken Content → System Voice → Manage Voices →
download an **Enhanced** male voice (e.g. *Aaron*, *Rishi*), then `export SHERU_VOICE="Aaron (Enhanced)"`.

## Running on Windows (Satya 👋)

Straight up: most of Sheru is macOS-specific, so this repo is a **reference architecture to port**, not a
drop-in install for Windows. What each layer needs:

| Layer | Sheru (macOS) | Windows equivalent to build |
|---|---|---|
| Local LLM / STT / TTS | Apple MLX (`mlx-lm`, `mlx-whisper`, Kokoro) | **Ollama** or `llama.cpp` for the LLM; `faster-whisper` for STT; Piper / Edge-TTS for voice |
| GUI panel + menu bar | pyobjc / AppKit / rumps | **PySide6 / Qt** or Tkinter panel; `pystray` for the tray icon |
| Open / quit apps, terminal | `open -a`, Ghostty, AppleScript | `os.startfile` / `subprocess`, Windows Terminal |
| Music / messaging control | Spotify + WhatsApp AppleScript | Spotify Web API; WhatsApp Web via Playwright |
| Screen read | Apple Vision OCR | `pytesseract` / Windows.Media.Ocr |
| Escalate to Claude | `claude -p` CLI | **works as-is** if the Claude Code CLI is installed |

**Ports cleanly with no changes:** the tiered **router grammar** (`router.py`), the **tool schema** (`tools.py`),
the **Claude Code handoff** (`claude_code.py`), and the overall architecture — that's the valuable core. The
platform layer (`actions/`, `panel.py`, `tts.py`, `stt.py`, `audio.py`) is what you'd re-implement for Windows.

Suggested path: rename it to your own assistant, keep `router.py` + `tools.py` + `claude_code.py`, and rebuild
the `actions/` + GUI + model layers for Windows. Ping Yash and we'll merge learnings later.
