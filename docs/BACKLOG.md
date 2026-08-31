# Sheru — Backlog & Reference Index

Deferred / dropped ideas with pointers to the detailed docs, so a future request goes straight to the reference
instead of re-researching. **Status legend:** ✅ built · 🟡 partly built · 📋 spec'd, not built · 🔬 researched only
· 💡 idea. Newest research at the top of each section.

---

## macOS Shortcuts

### Power-user ideas (full brief: `docs/SHORTCUTS-POWER-USER.md`)
Researched 2026-08-31, tailored to Yash. Only **OCR** was built; the rest are documented, not built:
- 📋 **Start Work launcher** — open Ghostty/Docker/Zen/Obsidian/Spotify + Work Focus + volume; one hotkey. Sheru-runnable.
- 📋 **Night wind-down** (Time-of-Day ~2:30am, self-running) — Sleep/DND + Dark + volume down + Low Power. Body Sheru-runnable as "goodnight".
- 📋 **NITS-WiFi automation** (Wi-Fi-join) — set College Focus + **flip Sheru to browser-fallback tier** on campus (Sophos CA). Self-firing.
- 📋 **Screenshots watcher** (Folder trigger) — new screenshot → auto-OCR to clipboard / rename. Self-running.
- 📋 **Toggle Dark Mode**, **Now Playing (Spotify)**, **Run over SSH** (RunPod/box), **batch image resize/convert** (Finder Quick Action).
- Key macOS facts in the doc: Mac has **App-open/quit, Folder, File-change** triggers (new, dev-useful) + Wi-Fi/BT/Focus/Battery/Charger/Display; **NO location trigger, NO Alarm trigger** on Mac; automations can "Run Immediately" (silent).

### Shortcuts integration for Sheru (full spec: `docs/SHORTCUTS-INTEGRATION.md`)
- ✅ **`run_shortcut` bridge** — "run shortcut X" runs any Shortcut (fuzzy-matched, timeout-guarded).
- ✅ **Focus/DND + brightness by voice** — route to `Sheru Set Focus` / `Focus Off` / `Get Focus` / `Set Brightness` helper shortcuts (Yash creates these once; steps in the spec).
- ✅ **Window management** — via Rectangle URL scheme (no setup).
- ✅ **OCR "what's on my screen"** — built via Apple Vision (NOT a shortcut); `src/sheru/actions/screen.py`.
- 📋 **Proactive automations** — battery/time/app/focus triggers that call Sheru's socket. Not built.

### Native "Hey Sheru" wake word (deferred; spec in `docs/SHORTCUTS-INTEGRATION.md`)
- 💡 **Route A** — Vocal Shortcuts → Siri Request → a "Wake Sheru" shortcut (needs Siri enabled, unused).
- 💡 **Route B** — Voice Control → Custom Command → Run Workflow (no Siri, but hijacks the mic). Its Grid overlay = free mouseless clicking.
- Both validated to reach `sheru trigger` (absolute socket). Build an Automator "Wake Sheru" Quick Action when picked up.

---

## Audio front-end / speech capture
- ✅ **Voice-Processing I/O (AEC + AGC + noise suppression)** — mic capture routes through Apple's `AVAudioEngine`
  `setVoiceProcessingEnabled` (the front-end Siri/FaceTime use), replacing the raw sounddevice path + the OS-mic-gain
  hacks. `src/sheru/avcapture.py` (one shared VP engine — two conflict; PTT and the always-on listener coordinate
  via a ptt flag). Auto-falls back to sounddevice if the engine can't start (`SHERU_VOICE_PROCESSING=0` forces raw).
- ✅ **Silence/noise hallucination gate** — Whisper invents canned phrases on near-silence ("Thank you.", "I'm
  sorry. …"). Three layers: STT confidence gate (`compression_ratio > 2.4` / logprob / no-speech, `stt._hallucinated`),
  an energy floor before STT (`capture_once`), and the PTT loop treating empty text as a quiet window (no re-arm →
  can't spin). AGC amplifies room hiss, so these matter more with VP, not less.
- 📋 **Pin VP to the built-in mic** — the VP engine currently uses the **system default input** (correct for AEC,
  which pairs input+output). Yash's rule is "always built-in mic"; if a headset is ever the default, VP would grab
  it. To force built-in: set `kAudioOutputUnitProperty_CurrentDevice` on the input node's `auAudioUnit` (needs the
  built-in's `AudioDeviceID` via CoreAudio HAL). Not built — default-input is right for now.
- 💡 **Barge-in** — AEC now cancels Sheru's own TTS from the mic, so interrupting mid-reply ("Sheru, stop") is newly
  feasible. Today the always-on listener still drops audio while speaking (`is_busy`); lifting that + a fast
  "stop"-word check would enable barge-in.

---

## Mouseless / text-box control (full research: `docs/RESEARCH-mouseless-typing.md`)
🔬 Now buildable (Accessibility is granted). 469-line doc, API constants verified vs pyobjc. To build a `src/sheru/ax.py`:
- Reliable **WhatsApp send** — enable Electron AX tree, verify the composer loaded, `AXPress` the Send button (drop the blind sleep+Return in typing mode).
- **click-by-voice** ("click the Send button / click X") — enumerate `AXPress`-able elements, fuzzy-match the spoken label.
- Focus a specific text field, insert via `kAXSelectedText`. 5-step build order in the doc.

---

## Voice / assistant features (v2 asks — memory `sheru-feature-requirements`)
- 💡 **Generative-agent layer** — Claude writes code → scratchpad → offer to run/move, generalized.
- 💡 **Smart media / YouTube-by-channel** — "play the latest MKBHD" resolves by channel.
- 💡 **LRU file cache**, **voice UX overhaul** (follow-up listening, warming-up state — partly done).
- 💡 **Song identification (ShazamKit)** — Yash asked feasibility; SHManagedSession bridge. Offered, not built.

---

## Local models / LLM
- 🔬 **huihui-ai "abliterated" (uncensored) Qwen3** — evaluate as Sheru's local brain. huihui-ai publishes
  *abliterated* models (a technique that removes the refusal direction from the weights, so the model stops
  declining requests). Directly relevant: **`huihui-ai/Qwen3-4B-abliterated`** exists (Sheru runs Qwen3-4B), plus
  8B/14B/32B, MoE `Qwen3-30B-A3B` / `Qwen3.5-35B-A3B`, and **vision** `Qwen3-VL-4B/8B-Instruct-abliterated`
  (could feed the screen-vision sub-project). **Why for Sheru:** the stock Instruct model over-refuses casual /
  personal / Hinglish-slang asks (a personal assistant shouldn't). **Tradeoffs / gate before adopting:** (1) the
  HF release is `Qwen3-4B-abliterated` (base 4B, NOT the `Instruct-2507` variant Sheru chose for routing) — so it
  may REGRESS tool-routing; run it through `scripts/eval_router.py` and keep it only if it holds ≥ base (same
  eval-gate rule as fine-tuning). (2) abliteration can degrade instruction-following / structured tool-JSON —
  double-check with constrained decoding on the roadmap. (3) needs an **MLX 4-bit conversion** (`mlx_lm.convert`,
  or find an mlx-community abliterated build). (4) not safety-optimized — fine for a private local assistant, keep
  the pending-confirm gate for outward actions. Refs: [huihui-ai/Qwen3-4B-abliterated](https://huggingface.co/huihui-ai/Qwen3-4B-abliterated),
  [Qwen3-VL-4B-Instruct-abliterated](https://huggingface.co/huihui-ai/Huihui-Qwen3-VL-4B-Instruct-abliterated).

---

## Packaging / infra
- 💡 **Proper self-contained (non-alias) `.app`** — current bundle is py2app **alias mode** (references the venv). If it's ever rebuilt/re-signed the TCC identity can shift → a re-grant. A fully embedded bundle would make the identity rock-stable. Build files: `packaging/setup_app.py` + `sheru_app_main.py`.
- 🟡 **Fine-tuning** — kept base twice (overfits the narrow router; see `docs/FINETUNE-RESULT.md` + `docs/OVERNIGHT-LOG.md`). Honest gated pipeline + dataset ready in `data/finetune/` (gitignored). A retry needs a much larger, more diverse real corpus, not more iters.

---

## Other reference docs (already in `docs/`)
`JARVIS-ROADMAP.md` (phased roadmap) · `DESIGN.md` (screen-vision/MCP design) · `BROWSER-AND-IMPROVEMENTS.md`
(browser tiers, Sophos CA) · `JOURNEY.md` (origin story) · `finetuning-research.md` · `ORB-ANIMATIONS.md`.
