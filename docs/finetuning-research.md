# Sheru — fine-tuning & efficiency research (synthesis)

Consolidated from a 5-source sweep (repo-vet + efficiency, MLX fine-tune + prior-art, Reddit/HN,
X/blogs/YouTube, LinkedIn/Medium/ProductHunt), 2026-08-28. Goal: fine-tune the local model to the user's
command style and, if wanted, make a bigger model efficient — train on RunPod, infer locally on the M5 (16 GB).

## TL;DR

1. **Train on RunPod, serve on the M5.** Cloud does the memory-hungry training; the Mac serves a 4-bit model.
2. **Fine-tune a 4B, not an 8B.** Routing to ~7 tools is a narrow skill; after ~100–200 examples/tool a 4B
   matches an 8B on *your* commands at half the RAM and latency. Use **`Qwen3-4B-Instruct-2507`** (non-thinking,
   BFCL 61.9 — beats base 4B and even 30B-A3B non-thinking). Thinking models read their monologue aloud → latency.
3. **The dataset is the whole game**, and it's cheap: log real utterances → `claude -p` labels the correct
   tool-call JSON → nightly LoRA refit. ~700–1500 total examples. This is the proven Octopus-v2 / home-llm recipe.
4. **On RunPod use Unsloth** (2× faster, ~70% less VRAM) or Axolotl — better-established than Soup for Qwen3 LoRA.
5. **Reliability trick:** enforce valid tool-call JSON with a **grammar/constrained decoding**, fine-tune only for
   phrasing. Neither a bigger prompt nor fine-tuning guarantees valid JSON; a grammar does.

## 1. The repo you sent — "Soup" (verdict: RunPod-only, and not the first pick)

- **Original `MakazhanAlpamys/Soup` is real & credible** — Apache-2.0, 3.3k★, 961 commits, *reproduced* benchmarks
  (Llama-3.1-8B NF4 trained at 119 tok/s in **3.3 GB** on a 4 GB RTX 3050, bit-exact vs resident).
- **Layer-streaming is a discrete-VRAM trick** (stream one decoder layer at a time into a small VRAM pool). The M5
  has **unified memory** — no separate VRAM to stream into — so the feature is moot on the Mac; there Soup is just
  a thin `mlx-lm` wrapper. **It's a RunPod (NVIDIA) tool for this project.** Its own docs say streaming is BETA and *slower*
  wall-clock (a VRAM-ceiling bypass, not a speedup).
- **The fork you linked is stale** — 0★, 159 commits / 271 files behind upstream, no fork-only changes. Use upstream
  `MakazhanAlpamys/Soup` / PyPI `soup-cli` if at all. Safety: RUN_WITH_CAVEATS (clean Dockerfile, no telemetry; run
  in a disposable cloud container).
- **But for RunPod Qwen3 LoRA, Unsloth or Axolotl are the better-established choice** — Soup's headline feature
  doesn't help us and its MLX path adds nothing over `mlx-lm`.
- Not to be confused with **"model soups"** (weight-averaging, mergekit) — a different technique, same word (§5).

## 2. Model choice (16 GB reality)

| | Qwen3-4B(-Instruct-2507) 4-bit | Qwen3-8B 4-bit | Qwen3-30B-A3B 4-bit |
|---|---|---|---|
| RAM (weights) | ~2.5 GB | ~4.6 GB | ~17–20 GB — **won't fit 16 GB** |
| Decision latency (measured, M5) | 1.0–1.7 s | 1.9–2.4 s | n/a |
| Headroom w/ parakeet+Docker+Zen | comfortable | tight (swap risk) | — |
| Out-of-box judgement | good | better | best |
| **After fine-tuning on your data** | **≈ 8B on your commands** | marginal gain | overkill |

- **Now (un-fine-tuned):** 8B is the runtime default (better on fuzzy fall-through + offline general answers).
- **Fine-tune target / hot path:** 4B-Instruct-2507. Keep 8B or `claude -p` for offline general-knowledge answers.
- 30B-A3B MoE is a 32 GB+ luxury; skip on 16 GB.

## 3. Efficiency levers, ranked for our case (≤2 s/turn, 16 GB shared with STT+VAD)

1. **Right-sized 4-bit dense** (4B) — foundation.
2. **Stream to TTS at sentence boundaries** — the single biggest latency lever (turns ~8 s → ~1–2 s). Already done
   for the Claude path in `claude_code.py`; **extend to the local `answer()` path** (currently speaks in one shot).
3. **Prompt/KV prefix caching** — near-free TTFT cut for the fixed system prompt (`mlx-lm` prompt cache).
4. **Constrained decoding / grammar** for tool-call JSON — reliability, not speed. Make the router emit valid JSON
   every time instead of regex-extract-and-hope.
5. **Distillation** (Claude teacher → 4B student) — the real quality lever for the narrow task; offline cost only.
6. **Speculative decoding** — real but **modest for small models** (mlx-lm disc. #890: EAGLE-3 on M3 Ultra only
   1.05×; big gains are for *large* targets, e.g. 32B +81%). Needs a resident draft model (+RAM). **Skip for the 4B.**
7. **Quant <4-bit / MoE / pruning** — skip on 16 GB.
8. **Model soup (mergekit)** — optional cheap post-step: average 2–3 LoRA-fused variants; modest robustness bump.
9. **AirLLM-style inference layer-streaming** — never (~0.07 tok/s, disk-bound). (Distinct from Soup's *training* trick.)

## 4. The fine-tune recipe

**Base:** `Qwen3-4B-Instruct-2507` (4-bit MLX). Quality path if QLoRA underperforms: LoRA on bf16 → `mlx_lm.fuse`
→ `mlx_lm.convert -q` to 4-bit (avoids compounding quant noise; a QLoRA adapter can't cleanly fuse into a 4-bit base).

**Data (build from your usage + Claude labels):**
- Output format = **Qwen3/Hermes** exactly: tools in a `<tools>` system block (OpenAI `{"type":"function",...}` shape);
  model emits `<tool_call>\n{"name":..,"arguments":{...}}\n</tool_call>`; **`arguments` is a JSON object, not a string.**
- Seed 50–100 from `NousResearch/hermes-function-calling-v1` (Apache-2.0) to lock the envelope.
- Log every real Sheru utterance → nightly `claude -p` labels the correct call → mlx `tools`-format JSONL.
- 5–10 Claude paraphrases per seed (distilabel / Bespoke Curator); **hard negatives** (must route to a spoken
  answer, not a tool — the tool-vs-answer fork is the hardest decision); mix ~30–50% general chat (anti-forgetting).
- Target ~100–200 examples/tool → **~700–1500 total** (Octopus-v2: 100/fn → 98%). Split 90/5/5.

**Train (local M5, ~30 min):**
```
mlx_lm.lora --model mlx-community/Qwen3-4B-Instruct-2507-4bit --train \
  --data ./sheru_data --iters 1000 --batch-size 4 --num-layers 16 \
  --learning-rate 1e-5 --mask-prompt --grad-checkpoint
mlx_lm.fuse --model <base> --adapter-path adapters --save-path fused_model
mlx_lm.server --model fused_model      # OpenAI-compatible localhost
```
LoRA rank 8 (→16 if underfitting), few epochs, quantize-before (QLoRA auto if base is 4-bit).

**RunPod (only for bigger/bf16/8B or sweeps):** Unsloth on a 4090 (~$0.44/hr, <$1/run) → download → quantize to
4-bit MLX → serve locally. ~$2–3 for an A100 run.

**Eval gate:** held-out test through BFCL-style AST accuracy before shipping each adapter.
**Serve:** keep the fused model warm in `mlx_lm.server`; enforce JSON with a grammar at inference.

## 5. Prior art worth stealing (start with #1)

1. **acon96/home-llm** — THE template: small models (270M–5B) fine-tuned on synthetic (command → tool-call) data
   for smart-home routing, with an open data-gen pipeline + dataset. Closest working analog to Sheru.
2. **NexaAI Octopus-v2** — "functional tokens" + 100 samples/fn + *tool-baking* (schema in weights → ~95% shorter
   prompts, faster first token, higher accuracy). 0.38 s, 99.5%.
3. **Functionary (MeetKai)** — the "know when NOT to call a tool" negatives (82.8% BFCL).
4. **kwindla/macos-local-voice-agents** — proven **<800 ms** local Mac voice-to-voice (Silero VAD + MLX-Whisper +
   smart-turn + LLM + Kokoro via Pipecat). Reference pipeline.
5. **distil-labs / AIAnytime/distillanything / Kiln AI / OpenPipe** — distillation/trace-capture toolkits (Claude as
   teacher). distil-labs: 0.6B student 10% → 79.5% exact-match on smart-home routing, <50 ms local.
6. **Gorilla / BFCL** — use as the accuracy eval harness, not training data.

## 6. Voice/latency lessons (from people who shipped this)

- Stream LLM output to TTS at sentence boundaries — biggest single win (johnthenerd: 8 s → 1–2 s).
- **Wake word is the #1 unsolved pain** — open solutions ~30–50% reliable vs ~95% commercial; train a **custom**
  wake word (microWakeWord / livekit-wakeword, 200–400 personal samples across rooms/moods). Matches our Phase-1 note.
- **TTS naturalness is hard** — Piper/Kokoro sound robotic; **XTTS-v2 / voice-cloning** is the path to a convincing
  "smart teen boy" voice (relevant to the requested voice). Persistent warm TTS server = ~30× speedup.
- Enforce tool JSON with a grammar; validate on the *action* side (models hallucinate/misformat).
- Qwen3 > Llama-3.2-3B for tool reliability at this size.


## Sources (high-signal)
- Soup: https://github.com/MakazhanAlpamys/Soup · streaming gate: .../benchmarks/gate-v0.72.0-layer-streaming.md
- mlx-lm LoRA: https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md · spec-decode PR: https://github.com/ml-explore/mlx-examples/pull/1155 · reality check: https://github.com/ml-explore/mlx-lm/discussions/890
- Qwen3 tool template: https://qwen.readthedocs.io/en/latest/framework/function_call.html · model: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- home-llm: https://github.com/acon96/home-llm · Octopus-v2: https://arxiv.org/abs/2404.01744 · Functionary: https://github.com/MeetKai/functionary
- macos-local-voice-agents: https://github.com/kwindla/macos-local-voice-agents · distil-labs, Kiln: https://docs.kiln.tech/docs/fine-tuning/fine-tuning-for-tool-use · OpenPipe: https://github.com/OpenPipe/OpenPipe
- Unsloth: https://github.com/unslothai/unsloth · Axolotl: https://github.com/axolotl-ai-cloud/axolotl · mergekit: https://github.com/arcee-ai/mergekit
- kdnuggets MLX FT: https://www.kdnuggets.com/fine-tuning-language-models-on-apple-silicon-with-mlx · hermes data: https://huggingface.co/datasets/NousResearch/hermes-function-calling-v1
