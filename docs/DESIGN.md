# Sheru — Master Design & Requirements

The single source of truth so nothing is forgotten. Captures every requirement, decision, and status from
the build. Update the **Status** column as work lands. Companion research: `docs/finetuning-research.md`.

Legend: ✅ done & tested · 🟡 partial/needs live test · ⬜ not started · 🔬 needs research/decision

---

## 0. Vision

Sheru = a Siri-replacement voice assistant **and companion** on macOS (M5, 16 GB). Wake word **"Hey Sheru"**
(pronounced *Sheroo*). Talk to it or type to it; it opens/controls apps, chats, searches + summarizes, plays
music, drafts + sends messages, remembers facts, learns over time, and hands hard work to Claude. Warm, fast,
private. User: Yash, in Ravangla, Sikkim.

---

## 1. Voice & I/O

| Feature | Status | Notes |
|---|---|---|
| Wake word "Hey Sheru" (hands-free) | ✅ | Transcript-based detection; regex accepts sheru/sheroo/sharu/shiru/cheru |
| STT (on-device) | ✅ | parakeet-mlx, ~80 ms, English; no ffmpeg (reads numpy directly) |
| VAD | ✅ | silero via sherpa-onnx |
| TTS voice | 🟡 | Rishi (en-IN male) pitched 1.22 as placeholder. **Want: smart teen-boy voice** — needs an Enhanced male voice download, or ElevenLabs kid voice (paid, +300 ms). Configurable via `SHERU_VOICE`/`SHERU_PITCH` |
| Type-to-Sheru silent panel | 🟡 | Glassy `NSVisualEffectView` panel built; needs live visual check. Hotkey trigger pending activation build |
| Follow-up window (no wake word after a reply) | ✅ | ~6 s |
| Speaker stuck-guard (mic can't freeze on hung TTS) | ✅ | 30 s cap |

---

## 2. Brain / routing

Tiered router: **Tier 0** deterministic grammar (instant) → **Tier 1** local LLM (routing + light chat) →
**Tier 2** Claude Code / browser / native control.

| Feature | Status | Notes |
|---|---|---|
| Tier 0 grammar | ✅ | open/quit/switch, volume, media, timer, clipboard, search, images, URL, weather, summarize, play_song, remember, set_location, message, setup |
| Tier 1 local LLM | ✅ | **4B default** (`Qwen3-4B-4bit`) — freeze fix on 16 GB; `SHERU_LLM=…8B` to revert. `enable_thinking=False` |
| Tier 2 Claude Code (`claude -p`) | ✅ | Subscription auth; streams to TTS/panel; 150 s watchdog; 5-min cooldown + local fallback on failure |
| Current-info / weather / summarize → Claude | ✅ | Was faked by 8B; now delegates and answers for real (verified: Ravangla weather) |
| Anti-hallucination prompt | ✅ | Never "processing…"/"I'll do it" — call a tool or say it can't. Companion tone |
| Memory (instant fact store) | ✅ | `memory.py`; inject-all-when-small; "remember X" tool + grammar |
| Journal (every interaction + feedback + latency) | ✅ | `journal.jsonl`; correction/cancel → prior turn negative; per-request latency logged |
| Location (profile-authoritative) | ✅ | Ravangla, Sikkim in gitignored profile; IP fallback; "set my location to X" updates it |

---

## 3. Actions & app control  ← the current focus

**Control ladder** (prefer the highest that works): deterministic → **native app (AppleScript / accessibility /
mouseless)** → **Claude-in-Chrome** (web, uses your logins) → vision (last resort).

**DECISION (Yash):** for apps he uses daily (esp. **Spotify — the native Mac app**), control the real app via
accessibility/mouseless, **not** web APIs (per-action API code = friction for "add to playlist/favourites").
Prefers the native app for its own UX. OK with setup overhead for the best end experience. No Homerow yet — use
the accessibility tree, and **build custom mouseless tooling if the tree is insufficient**.

| Action | Status | Notes |
|---|---|---|
| open/quit/switch app, volume, timers, clipboard, URLs | ✅ | deterministic |
| web search (localized) + image search | ✅ | opens browser |
| draft → confirm/rephrase → send message | 🟡 | flow works (tested, send stubbed); real send needs live test (iMessage AppleScript best-effort → pre-fill fallback) |
| play/pause/next (Spotify) | ✅ | AppleScript |
| **play a specific song** (Spotify) | 🟡 | Currently opens in-app search (no autoplay). **API path rejected by Yash.** Feasible native path below |
| **add to favourites / playlist, search-and-play** (Spotify) | 🔬 | **BLOCKED via accessibility**: Spotify is Electron — probe shows only the menu bar (182 items) is exposed; the UI body is one opaque AXGroup. Need: AppleScript (playback only) + **System Events keystroke nav** (Cmd+L search → type → Enter) + **vision/computer-use** for playlist/favourite buttons. Or a **custom mouseless overlay** we build |

### Sub-project: `sheru-vision` — screen perception + control service (the native-control foundation)

**DECISION direction (Yash's idea, validated):** rather than fragile per-app integrations, build ONE local
service that reads the screen and exposes it as an API — the Claude-Code + Claude-in-Chrome pattern, but for the
whole desktop. Sheru's tools call it; **and it's exposed as an MCP server so `claude -p --mcp-config` gives Claude
its own eyes+hands on the Mac** (Claude Code orchestration + screen tool = computer-use, ours, local).

**VALIDATED 2026-08-28:** Apple **Vision OCR reads Spotify content the accessibility tree can't** — captured a real
song title ("You Belong with Me (Taylor's Version)") from Spotify's opaque Electron body. So AX-blind apps are
readable via OCR.

API surface:
- `read_screen(app?)` → unified element list: **AX tree** (semantic, native apps + any app's menu bar) **+ Vision
  OCR** (text + bounding boxes, for Electron/canvas) + optional screenshot. Each item: label, role, bbox.
- `find(query)` → best element/text match + coords.
- `screenshot()` → image for a vision model when AX+OCR aren't enough.
- `click(target)` / `type(text)` / `key(combo)` → act.

Honest engineering reality:
- **Reading = solid** (AX ~50 ms + Vision OCR ~0.5 s + screenshot). Per-window full-res capture for clean OCR.
- **Acting on Electron content = the hard part.** Native/menu-bar → `AXPress`. Electron body (Spotify) has no AX
  elements → click by **coordinate** from the OCR/vision bbox. Tahoe filters synthetic `CGEvent` from UNSIGNED
  procs → **requires the signed `.app`** (which we need anyway) + Retina 2× coord mapping. Menu-bar + AppleScript
  cover Spotify playback today; search/favourite/playlist come via OCR-locate → coordinate-click once signed.
- Vision fallback (Anthropic computer-use) only when OCR/AX insufficient.

Components: `actions/native.py` (AX tree + AXPress + menu-bar), `vision/ocr.py` (Vision OCR + bboxes),
`vision/capture.py` (per-window Retina screenshot), `vision/act.py` (coordinate click/type — signed app),
`vision/mcp_server.py` (expose read/find/click/screenshot as MCP for Sheru + Claude).

**Claude-in-Chrome lane** (web tasks where Yash is logged in — forms, sites, booking): 🔬 delegate "do X on the web"
to Claude-in-Chrome. Yash will handle logins. Needs the extension + site permissions. Not for Spotify (he wants native).

---

## 4. Siri replacement / activation

**DECISION (Yash):** full takeover — disable Siri + Hey Siri, free its shortcut, **hold the F5 🎤 key for
push-to-talk**. Show each system change before applying.

| Item | Status | Notes |
|---|---|---|
| Disable Siri + free shortcut | ⬜ | System Settings → Apple Intelligence & Siri (GUI authoritative; not scriptable on Tahoe). Ordered checklist in research |
| Hold F5 mic key = PTT | 🔬 | Via Karabiner → `sheru://ptt-down`/`ptt-up`. **RISK: macOS 26.4+ breaks Karabiner remap of the BUILT-IN keyboard** (DriverKit) — Yash is on 26.6.2. Needs a 2-min interactive F5 check. Fallback: in-process `RegisterEventHotKey` (zero TCC) on a bindable combo |
| `sheru://` URL scheme + global hotkey | ⬜ | RegisterEventHotKey (Carbon, no TCC) as primary; URL scheme for the Karabiner bridge |
| Can't replace | — | No macOS "default assistant" API; hardware Siri button / Touch Bar / "Type to Siri" not reassignable |

---

## 5. Setup / onboarding

| Item | Status | Notes |
|---|---|---|
| Permission probes (mic/accessibility/automation/screen) | ✅ | Read-only status via pyobjc; all 4 currently GRANTED |
| Terminal wizard (`uv run sheru setup`) | ✅ | Works but Yash found it "weird" + it spawned many terminals |
| **In-app onboarding WINDOW** | ⬜ | **BUILD THIS** — glassy window: intro, per-permission status + Grant buttons (live re-check), location, capabilities. No terminal |
| Voice "run setup" spawning terminals | ✅ fixed | Now just guides; menu launch debounced |

---

## 6. Learning / self-improvement

| Item | Status | Notes |
|---|---|---|
| Journal + feedback capture | ✅ | raw material accumulating from real use |
| Memory (facts) vs fine-tune (skills) — two mechanisms | ✅ designed | active/online weight-learning is NOT safe; batched retrain is the real thing |
| Nightly curate (`claude -p` labels journal → dataset) | ⬜ | `curate.py` |
| Weekly LoRA retrain + eval gate + adapter swap/rollback | ⬜ | RunPod (Unsloth) or local; **RunPod MCP now CONNECTED** |
| Base model for fine-tune | 🔬 | 8B if chat matters; 4B if routing-only. Distill Claude's routing. See finetuning-research.md |

---

## 7. Model / performance

- **4B default** (freeze fix): 8B on 16 GB + apps → 2 GB swap → minute-long stalls when weights page back.
  4B ≈ 2.5 GB, faster. Revert: `SHERU_LLM=mlx-community/Qwen3-8B-4bit`.
- Per-request latency now in the journal to confirm any residual stall.
- Optional later: speculative decoding (modest on small models), prompt/KV prefix caching.

---

## 8. Packaging / distribution

| Item | Status | Notes |
|---|---|---|
| uv project, Python 3.12 | ✅ | |
| Menu-bar app (rumps) + template icon | ✅ | waveform template icon (was broken 🦁 emoji) |
| Signed `.app` (py2app) + LSUIElement + Login Item | ⬜ | needed for stable TCC identity + launch-at-login |
| **GitHub push** | 🟡 prepped | data/ gitignored, de-personalized, MIT LICENSE, cleaned. **Pending Yash's 4 answers**: public/private, repo name (`sheru`?), license email, push to `intotheabyss19` |
| Ghostty tab-cloning on new window | 🟡 fixing | `open -na` new instance restores the whole session; fix = `--window-save-state=never` (+ onboarding moves in-app so terminal rarely opens) |

---

## 9. Prioritized build order (next)

1. **In-app onboarding window** (§5) — removes the terminal friction; Yash asked explicitly.
2. **Ghostty tab-clone fix** (§8).
3. **Spotify native control** (§3): `actions/native.py` (menu-bar + AX), AppleScript playback, keystroke
   search-and-play, honest vision fallback for favourites/playlists. Test against real Spotify.
4. **Activation** (§4): F5/Karabiner 2-min check → wire PTT (in-process hotkey fallback) + `sheru://` scheme.
5. **Disable Siri** guided flow (§4).
6. **GitHub push** (§8) — on Yash's 4 answers.
7. **Message send** live test (§3); **teen-boy voice** (§1).
8. **Self-improvement loop** (§6): curate + retrain on RunPod.
9. **Signed .app** packaging (§8).
10. **Fine-tuning** (§6/research) once the journal has data.

---

## 10. Open decisions needing Yash

- GitHub: public/private, repo name, license email, confirm `intotheabyss19`.
- Fine-tune base: 4B vs 8B (revisit after 4B daily use).
- Teen-boy voice: download an Enhanced male voice ($0) vs ElevenLabs (paid, best).
- Claude-in-Chrome: confirm installed + which web tasks to route there.
