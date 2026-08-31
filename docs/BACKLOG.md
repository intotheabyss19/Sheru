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

## Packaging / infra
- 💡 **Proper self-contained (non-alias) `.app`** — current bundle is py2app **alias mode** (references the venv). If it's ever rebuilt/re-signed the TCC identity can shift → a re-grant. A fully embedded bundle would make the identity rock-stable. Build files: `packaging/setup_app.py` + `sheru_app_main.py`.
- 🟡 **Fine-tuning** — kept base twice (overfits the narrow router; see `docs/FINETUNE-RESULT.md` + `docs/OVERNIGHT-LOG.md`). Honest gated pipeline + dataset ready in `data/finetune/` (gitignored). A retry needs a much larger, more diverse real corpus, not more iters.

---

## Other reference docs (already in `docs/`)
`JARVIS-ROADMAP.md` (phased roadmap) · `DESIGN.md` (screen-vision/MCP design) · `BROWSER-AND-IMPROVEMENTS.md`
(browser tiers, Sophos CA) · `JOURNEY.md` (origin story) · `finetuning-research.md` · `ORB-ANIMATIONS.md`.
