# Sheru — hands-free personal assistant for macOS

Wake word **"Hey Sheru"** (say *Sheroo*). Speaks back in a young male voice.
Tiered brain: instant grammar → local Qwen3-8B → Claude Code (your subscription) with a local fallback.

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
| `SHERU_STT` | `parakeet` | speech-to-text backend |

**Better voice:** System Settings → Accessibility → Spoken Content → System Voice → Manage Voices →
download an **Enhanced** male voice (e.g. *Aaron*, *Rishi*), then `export SHERU_VOICE="Aaron (Enhanced)"`.
