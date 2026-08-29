# Sheru → JARVIS: phased development roadmap

*Synthesis of deep research (Aug 2026) + the current codebase. Goal: get Sheru as close to how Iron Man uses
JARVIS as is realistically feasible for a solo dev on a 16GB M5 MacBook Air.*

## The honest verdict
**~70% of "JARVIS" is buildable today**; the sci-fi 30% (continuous ambient scene understanding, reliable
open-ended autonomy) is not — so we don't promise it. What IS shippable: personality + a great voice,
tiered local→cloud delegation (Sheru already has this), on-demand screen vision, deterministic Mac control,
bounded proactivity (briefings), and web-as-free-compute. The two cautionary tales that shape the design:
**Humane** (died when its cloud vanished → *stay local-first, never hard-depend on a cloud*) and **Rabbit R1**
(over-promised open web-agent autonomy → *keep tasks bounded and gated*).

**The blueprint to copy:** Home Assistant Assist's two-tier "fast intent match → LLM fallback" — which is
exactly Sheru's regex → local-LLM → Claude ladder. We extend it with a **browser tier** and a **screen tier**.

**Latency is the make-or-break number:** humans hand off turns in ~200ms. 200–500ms feels natural, 500–800ms
noticeable-OK, >1.5s feels broken. Full local stack on Apple Silicon fits sub-1s. **Stream TTS from the first
tokens** (HA reports ~10× faster *perceived* response) — non-negotiable for feeling live.

---

## Architecture (target)

```
mic → VAD (silero) → wake word ("Hey Sheru") → STT (Whisper hi/en) ─┐
                                                                     ▼
                        ┌──────────────────────── ROUTER ─────────────────────────┐
 Tier 0  regex grammar          instant, deterministic (open/play/timer/alarm…)    │  <200ms
 Tier 1  local Qwen3-4B (MLX)   tool-call w/ GRAMMAR-CONSTRAINED decode + memory    │  0.3–1s
          confidence gate: escalate on invalid-JSON / low token-margin / risky/multi-step
 Tier 1.5 BROWSER tier          search-API/SearXNG + Trafilatura + local summarize, │  1–4s
          (the user's key idea)  or drive a logged-in Chrome (duck.ai / read pages) — free compute
 Tier 2  Claude (kept WARM)     hard reasoning, live web, long-horizon; prompt-cached│  1–3s stream
 Tier 3  Screen/GUI control     AX-first click → Holo1.5-3B grounder → hand web to Claude
                        └──────────────────────────────────────────────────────────┘
                                       ▼ actions           ▼ reply: streamed TTS (Kokoro), barge-in
```

One resident local model (4B) + **cloud Claude as the only "big" arm** — 16GB has room for one LLM + STT +
(later) a 3B vision grounder, not two chat LLMs. All heavy ensembling happens in the cloud arm.

---

## Phase 0 — Foundation fixes ✅ DONE (this session)
- **Claude escalation repaired** (pinned `~/.claude-ashish`; the org-block was the #1 dumbness cause).
- **Continued-conversation memory** (all-tier history + Claude session resume) + the busy-race bug.
- **Hindi STT**: Whisper default + language clamp to {en,hi} + anti-hallucination opts (fixes "heard as Russian").
- **Alarms**: real looping bell + menu-bar list + "set an alarm" + voice dismiss.
- **Panel flash fixed** (global click-away monitor, no fade); **Siri message card**; **Spotlight recents**.
- **Local weather/files** (no Claude needed); **escalate-don't-guess** prompt.
- **Kokoro TTS wired** (opt-in; needs one-time spaCy fetch on clean network).

---

## Phase 1 — The voice *feel* (highest JARVIS-per-effort)
Goal: sub-1s, natural, interruptible, hands-free. This is what makes it *feel* like JARVIS.

1. **Kokoro-82M TTS as default** (`am_michael`; Hindi `hm_omega`/`hf_alpha`). Already wired — flip
   `tts_backend=kokoro` once the one-time `misaki`/spaCy fetch completes on home wifi. Add the **kokoro-onnx +
   CoreML** fallback for the known MLX NaN bug. **Stream per-sentence to audio** (Kokoro yields per-sentence).
2. **Whisper Hindi STT**: ship `whisper-large-v3-turbo` (done); optionally convert **`Trelis/whisper-hinglish-preview`**
   for best code-switch WER (13.7% vs 29.7% base). Keep the {en,hi} clamp + **silero-VAD gating** (the #1
   hallucination fix — never transcribe silence).
3. **Wake word "Hey Sheru"** (openWakeWord; target FA <0.5/hr, FR <5%) alongside push-to-talk. Record room-noise
   + Hindi-chatter negatives.
4. **Barge-in**: VAD stops TTS the instant the user speaks. Keep an adjustable end-of-turn wait (1.5–2.0s).
5. **Kid voice (cosmetic, later)**: Kokoro voice-blend toward a lighter timbre, or Praat/`parselmouth` pitch
   **+** formant shift together (+3–5 semitones, formants ×1.1–1.2). No off-the-shelf child voice exists.

## Phase 2 — Reliability & routing (make it *smart*, not just fast)
1. **Grammar-constrained tool JSON** via **Outlines + mlx-lm** — the single biggest accuracy-per-effort win; a
   constrained 3–4B rivals an unconstrained 70B on *structural* correctness. Keep the grammar **wide** (allow the
   no-tool/free-text branch) so it doesn't suppress "just answer" — constrain args only once a tool is chosen.
2. **Confidence-gated escalation** done right: **don't** ask the model "how sure are you"; gate on (a) grammar/
   tool-call validity, (b) token-margin/logprob from mlx-lm, (c) risk/multi-step. One local repair retry, then
   escalate.
3. **Keep Claude WARM** — do NOT cold-spawn `claude -p` per turn (~12s spawn overhead). Hold a persistent
   streaming session; put the system prompt + tool defs behind a **prompt-cache breakpoint** (~90% cost, ~85%
   latency cut on escalations). Precompute the local model's system+tools **KV cache at warmup**.
4. **Browser tier (your idea — big lever, esp. behind Sophos):**
   - **First, fix the cert story**: export the Sophos CA into a bundle, set `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE`
     — this alone may resurrect `claude -p` and any HTTPS API from Python behind the firewall (the browser works
     only because it trusts the Keychain CA; Python's certifi doesn't).
   - **Primary web-answer path**: search API (Brave ~1k free/mo) or local **SearXNG** → **Trafilatura** extract →
     **local 4B summarize** → speak. Silent, TOS-clean, API-key-optional. This is the Siri "here's what I found"
     fallback for weather/news/facts.
   - **Free-frontier-compute path**: drive a **dedicated, pre-logged-in Chrome** (Playwright over CDP; Chrome-136
     needs a non-default `user-data-dir`) to query **duck.ai** via DOM (no login, computes its own anti-bot) or
     read Cloudflare-gated pages. **Never automate Gemini** (account-lock risk); only drive already-authenticated
     tabs. Present silent-fetch → short spoken summary + source; gate any window-raising behind voice-confirm.
5. **Ensemble that fits 16GB**: regex tier + one 4B (constrained) + few-shot **self-verification** (same model) +
   a tiny **RouteLLM-style classifier** to fast-path obvious-cloud queries + Claude as the heavyweight verifier.
   No second resident LLM.

## Phase 3 — Capabilities & memory (make it *useful*)
1. **Memory = RAG, not weights**: durable facts/preferences in a store (Mem0/Cognee-style), hybrid semantic+keyword
   retrieval, injected per-turn. Trivially editable/deletable ("forget that"). Weight updates only for stable
   behavioral drift (Phase 6).
2. **Bounded proactivity**: a morning briefing (calendar + mail + weather synthesized by Claude) + a few event
   triggers. Keep it a *pulse* — over-eager proactivity is the fastest way to get muted.
3. **More tools via MCP** with **tool-retrieval** (embed tool descriptions, inject only the top-k) once you pass
   ~15–20 tools — else you burn context. Present self-built skills as **Shortcuts/AppleScript/MCP** code
   (Voyager-style skill library) so they're inspectable and runnable without the model.
4. **Alarms** ✅ (done) — add snooze + a Siri-style "alarm set" card + persistence across restart for alarms.

## Phase 4 — Screen comprehension + mouseless control (the "does things on my Mac" leap)
1. **Perception**: merge **AX tree** (`macapptree`/pyobjc; force-enable `AXManualAccessibility` on Electron) +
   **Apple Vision OCR** (`ocrmac`, ~130–200ms) + **ScreenCaptureKit** grab, deduped by bbox IoU. (Only ~33% of
   apps expose full AX — OCR fills the rest; this is Sheru's validated `sheru-vision` design.)
2. **Acting**: **AX-first deterministic click** — enumerate actionable elements (the Homerow/Shortcat mechanism,
   agent-driven), match intent→label/role, `AXPress` (cursorless, works on background apps). **CGEvent** fallback
   for AX-poor targets, with the Retina ÷2 point↔pixel mapping.
3. **Local grounder for AX-blind UIs**: **Holo1.5-3B** (MLX 4-bit, ~3–4GB, ScreenSpot-Pro 51.5%) resident;
   **Holo1.5-7B** (`mlx-community/holo1.5-7b-mlx`, 57.9%) load-on-demand.
4. **Hand off**: web → Claude-in-Chrome (DOM-grounded); dense/multi-step/cross-app → Claude computer-use. Realistic
   bar: native AX apps ≈ exact; Electron/web ~50–60% ceiling; long-horizon compounds errors — verify + retry.
5. **Reuse**: evaluate **trycua/cua** (native macOS driver, cursor/focus-preserving, ships an MCP server) as the
   action substrate before hand-rolling. **Requires a signed + notarized `.app`** (Tahoe filters synthetic events
   from unsigned procs; TCC grant keyed to the signing identity survives updates only if signed).

## Phase 5 — Self-improvement loop (how Claude actively makes Sheru better over time)
The escalation log is a **free, perfectly-targeted training set** — every turn Sheru escalated to Claude is a
labeled hard case. Run this as a **nightly cron** (NVIDIA's 6-step LLM→SLM loop, run continuously):
1. **Telemetry**: log every turn — utterance → tools shown → chosen tool-call → executed? → outcome → escalated?
   (Sheru already journals; extend it.)
2. **Auto-detect failures**: JSON-invalid, tool error, user retry/rephrase, thumbs-down, and **any escalation**.
   Cluster them to find recurring gaps.
3. **Claude-as-trainer session** (Sheru already opens one on request): reads failure clusters + code + traces →
   (i) repairs hard cases into clean gold tool-call traces, (ii) proposes prompt/grammar fixes (often no training
   needed — DSPy/GEPA-style), (iii) flags unmet requests → drafts a **new tool** (Shortcut/AppleScript/MCP stub).
4. **Nightly LoRA refit** locally in MLX on the repaired traces (+5–10% general-chat replay). Cheap (dozens of
   examples).
5. **Offline eval gate** before promoting: BFCL subset + your **private held-out tool suite** + a **regression
   set** of previously-passing cases (guards forgetting). Promote only if it beats new cases *and* doesn't regress.
6. **Canary + rollback**: promote behind a flag / shadow-run; auto-rollback on regression; every adapter
   git-tracked. **New tools = human-approved** (they're code that touches your machine). Prompt/grammar tweaks
   that pass the gate can auto-apply.

## Phase 6 — Fine-tuning (only for the semantic gap grammar can't fix)
- **Do grammar-constrained decoding + a strong prompt + tool-retrieval FIRST** — captures most of the gain at
  zero training cost. Fine-tune only when *semantic* errors persist (wrong tool, hallucinated args, fails to
  abstain, multi-turn confusion) and you have >~50–100 clean traces/tool.
- **Recipe**: distill Claude → clean traces (dedup/cluster; ~30–100/tool, spanning easy/ambiguous/no-tool/
  multi-tool + negatives); LoRA **r=16, α=32, all linear modules, LR 2e-4, 2 epochs, 5–10% chat replay**; eval on
  **BFCL** + private set. Distillation caveat: measure against ground-truth execution, not the teacher.
- **Where**: first big distillation SFT on **RunPod/Unsloth** (fast/cheap); **nightly personal refits local in
  MLX** (`mlx_lm.lora`, privacy, no egress). `mlx-tune`/`unsloth-mlx` mirror the API so you write once.
- **Best realistic expectation**: a constrained + lightly-tuned 4B handles the daily agentic load reliably;
  everything hard escalates to Claude. Don't chase a bigger local model — 8B routes the same as 4B (measured),
  9B risks RAM swap. The wins are plumbing + grammar + the cloud arm, not parameters.

---

## Requirements you might've forgotten (from the capability research)
- **On-device vs cloud data boundary** — write down what NEVER leaves the Mac (raw audio, transcripts) vs the
  minimal redacted task text that may go to Claude. This is the anti-Humane stance.
- **TCC permissions are a project, not a checkbox** — Mic, Accessibility (control), Screen Recording, EventKit
  (Calendar/Reminders/Contacts), Automation; each a separate grant. Needs the signed `.app` (Phase 4).
- **Confirmation gates as a CODE boundary**, not a prompt — map every tool to a risk tier; unknown tool → highest
  restriction; halt into `pending_approval` before side effects. (Sheru has the pending-confirm state machine.)
- **Cost controls** on Claude (daily/monthly token cap + per-escalation logging of *why* it escalated).
- **Observability** — log wake trigger, transcript, route decision, tool calls, approvals, latency per stage.
  Can't tune wake-word FA or latency without it.
- **Kill switch + mic-mute + a visible listening indicator** — always-listening lives or dies on trust.
- **Personality as editable config** (system prompt + swappable voice), never leaking banter into risky paths.

## UI/UX north star
Non-activating panel (typing panel needs key; a pure *listening* HUD should NOT steal focus). Live **waveform +
start earcon** for listening; **stream** partial ASR then reply; Raycast-style **toast (green ✓ / red ✗) while
open, bottom HUD pill when closed**; **assume success, confirm loudly only on failure**; respect
**reduce-motion / reduce-transparency**; semantic `NSColor` for dark mode. Update UI **only on the main thread**
(AppHelper.callAfter). Don't impersonate Siri (no orb, no name).

## Model / RAM budget (16GB)
macOS ~3–4GB + Whisper ~1.5GB + 4B ~2.5GB = ~7–8GB always gone. Fits: the 4B + STT + a **3B vision grounder
(~3–4GB) load-on-demand**. Does NOT fit: two resident chat LLMs, or a 9B resident with a browser open (swaps).

## Open decisions for you
1. **Wake word phrase** — "Hey Sheru" vs push-to-talk-only for now?
2. **Browser tier**: do the **Sophos CA → SSL_CERT_FILE** fix first (may un-block `claude -p` + APIs from Python)?
3. **Signed `.app`** — needed for Phase 4 (screen control) + durable TCC. Get a Developer ID?
4. **Kokoro default** once the one-time fetch lands on home wifi?

*Sources: consolidated from 7 research briefs (Aug 2026) — HA Assist, FrugalGPT/AutoMix/RouteLLM, Outlines-MLX,
Whisper/Kokoro/mlx-audio, Holo1.5/trycua-cua, BFCL/Voyager/NVIDIA-SLM, Trafilatura/duck.ai, Raycast/Superwhisper
UX + MenubarCountdown. Full citations in the session transcript.*
