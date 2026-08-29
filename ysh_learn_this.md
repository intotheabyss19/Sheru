# How to use Sheru well (Yash — start here)

Sheru understands **plain commands best**. Below are the phrasings that hit the fast, reliable path (Tier-0
grammar). You don't have to memorize them — near-variants work — but these never miss.

## The #1 thing: speak clearly, one command at a time
Most "it did the wrong thing" moments are **speech-to-text**, not Sheru being dumb. It mishears, especially
Hindi. Tips:
- **Press F5, wait a beat, then speak one clear command.** Don't trail off or repeat yourself.
- For **Hindi songs/names**, expect the local model to sometimes mis-hear. If a Hindi command misfires, the
  accurate fix is the **Sarvam voice/ears** (cloud) — say *"use the Sarvam voice"* (see Voice below), or ask me
  to switch STT to Sarvam. Local Whisper is free but shaky on Indian Hindi.
- You can always **type** instead of speak (Type-to-Sheru) — zero STT error.

## Apps (local)
- "open Spotify" · "open WhatsApp" · "quit Discord" · "switch to Obsidian" · "open the terminal"

## Music
- "play **Dandelions**" → Spotify if it's confident, else YouTube (never a dead-end)
- "play **tum hi ho** on YouTube" · "youtube lofi hip hop" · "play despacito on YouTube Music"
- "play **X** on Spotify" → forces Spotify · "pause" / "next" / "play"

## Messages (WhatsApp is your default)
- "message **Piyush** that I'll be late" · "whatsapp **Sourav** the meeting moved to 5"
- "message **Aditi** on LinkedIn saying great post" (opens LinkedIn + copies the text to paste)
- Your **454 contacts are loaded**, so names resolve. It reads the draft back and **asks before sending**.

## Alarms / timers / reminders (rings a bell)
- "set a timer for 10 minutes" · "set an alarm for **quarter past seven**" · "wake me at **half past six**"
- "remind me to call mom in an hour" · "remind me to take medicine at 9 pm"
- When it rings: say **"stop"** or click **Stop** in the menu bar.

## Web / info
- "what's the weather" / "what's the weather in Tokyo" (silent, spoken back)
- "search for best ramen in Delhi" · "show me pictures of tigers"
- "who won the India match" / "what's the SBI share price" → it fetches (via Claude) instead of guessing

## Email (local — Apple Mail has your Gmail)
- "open gmail" / "check my email" → opens **Apple Mail**
- "email **piyush** saying thanks" → opens a Mail draft (you review + send)

## Browser & profiles
- "use **Brave**" / "use Chrome" / "use Zen" · "use **piyush's** profile" / "use **moon's** profile"
- Zen = simple opens; Brave (piyush) = the automation browser (YouTube, etc.)

## Files / terminal (local)
- "make a folder called invoices on desktop" · "create a file called notes.txt" · "open a terminal in projects"

## Voice & language (change anytime, no restart)
- "**use the Sarvam voice**" (best Indian, cloud) · "**use the local voice**" (Kokoro, free) · "use the system voice"
- "**reply in Hindi**" / "reply in English" / "reply in both" (mirrors what you speak)

## Get me to fix Sheru
- "**open your trainer**" / "get your trainer to fix `<thing>`" → opens a Claude session on Sheru's own code.

## Local vs browser (what Sheru knows)
Local apps: **WhatsApp, Spotify, Apple Mail, Calculator/Finder/etc.** Browser (Brave/piyush): **YouTube,
LinkedIn, web search, Gmail-in-browser if you ask for it**. Say "…in the browser" to force the web version.

---
*If something misfires, tell me the exact words you said — I read `data/actions.log` (every input → what Sheru
did) and fix the routing. Run `uv run python scripts/review_logs.py` to see the fix-list yourself.*
