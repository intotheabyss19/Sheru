# Overnight work log — for Yash (waking ~9am)

Autonomous session: improve Sheru + GUI, add personality, fix issues, test, research, fine-tune.
Times are local. Newest at the bottom.

## TL;DR (good morning ☀️)
- **Theme: made Sheru far more LOCAL-first** (your core success bar). Informational questions, currency,
  weather, news, "who/what is X", and changing stats (GDP/population) now answer **on-device** — verified
  6/6 real escalations from your usage log now resolve locally, no Claude.
- **New on-device answerers**: exact FX (Frankfurter), weather (Open-Meteo + your location), news (Google
  News RSS), Wikipedia — plus a DuckDuckGo-lite fallback so a blocked endpoint doesn't force a Claude call.
- **Personality/pride** added to Sheru's system prompt (JARVIS-like, proud to be local).
- **Bugs fixed** (all found by testing + a fresh code audit, all verified): calc hijacking "volume 20 percent";
  spoken **number-words** ("five plus five", "convert hundred dollars") now work in calc/FX/volume; alarm/reminder
  parsing ("7 in the morning", "half an hour", "quarter past 7"); reminders keeping context ("...at the store");
  long answers cut off; **TTS no longer reads markdown/emoji aloud** ("asterisk asterisk").
- **Fine-tune**: ran a local LoRA, built an eval-gate, **kept the base model** — the adapter overfit and would
  have hurt (regressed chat + sent search to Claude). Details in `docs/FINETUNE-RESULT.md`. This is the correct,
  honest outcome; a real (non-synthetic) dataset is the next step if you want to retry.
- **Housekeeping**: Apache-2.0 license, ~18 focused commits on `overnight` (FF-merged to `main`, both pushed).
  **Sheru is running on the base model with all fixes live.** Nothing left playing/open from testing.
- **Try when you wake**: broken-English commands, "what's 100 dollars in rupees", "who is <someone>",
  "what's the news", "set an alarm for 7 in the morning", "five times five", "remind me in half an hour",
  "open a wikipedia page on black holes".
- ⚠️ **Heads-up: I left system volume at 8%** (your "≤10% during testing" rule) — turn it up to hear Sheru.

| Start | End | What I did | Result |
|---|---|---|---|
| 04:20 | 04:41 | Broken-English routing stress test (mocked, no real side effects) + fixes: 'stop the music' now pauses (was cancel), Hinglish 'bajao', 'make it loud'/'turn down sound', 'what time now', 'pics of X' | 6 misroutes fixed, no regressions |
| 04:41 | 04:44 | 'start a timer/alarm' → open-app misroute fixed; calc no longer fires on non-math ('add 2 apples and 3 oranges') | 2 real bugs fixed |
| 04:44 | 04:47 | Personality/pride added to Sheru's system prompt (confident, warm, JARVIS-like, proud to be local) | Live |
| 04:47 | 04:52 | 3 research agents (MLX fine-tuning, local-first techniques, codebase review) → acted on findings | Reports in hand |
| 04:47 | 04:52 | ★ Tier-1 routes info questions to LOCAL search (was Claude) + look_up tool — biggest local-first win | Verified: PM/population/iphone stay local, coding→Claude |
| 04:52 | 05:03 | Structured on-device answers: FX (Frankfurter), weather (Open-Meteo + your location), news (Google News RSS) — tried before scrape+summarize | Verified live: '$100→₹9539', 'weather→26° thunderstorms', news headlines. All local, no key, no LLM |
| 05:03 | 05:06 | decide() bug fixes: max_tokens 160→256 (long answers were cut off); never speak raw tool-call JSON/tags — escalate instead | Live |
| 05:06 | 05:11 | Audited real overnight usage log: 6 failures (euro→INR, $→₹, factorial 50, √5, SBI price, GDP) all now resolve ON-DEVICE (calc + structured FX + scrape). Verified end-to-end | 6/6 local, 0 regressions |
| 05:11 | 05:16 | Wikipedia structured answers: 'who is X'/'what is X'/'tell me about X' → crisp local 2-sentence facts (keyless REST). fx/weather/news still win for live data | Verified: Ada Lovelace, black hole, Turing all local |
| 05:15 | (running) | Started local LoRA fine-tune (Qwen3-4B-4bit, 8 layers, 400 iters, seq 2048) — app stopped to free RAM. Will eval-gate: deploy only if it beats base | val loss 2.32→0.023 @iter50; gate pending |
| 05:16 | 05:18 | Search robustness: DuckDuckGo Lite fallback so a blocked/changed HTML endpoint degrades locally instead of escalating to Claude | Verified: 13 lite results when HTML forced-fail |
| 05:18 | 05:21 | Fine-tune plumbing: serve LoRA adapter without fusing (config.LOCAL_ADAPTER) + eval_router.py held-out gate (deploy only if beats base) | Ready for post-training gate |
| 05:21 | 05:24 | Fixed 2 alarm/reminder bugs found by testing: 'N in the morning/evening/night' now parses; 'remind me in 2 hours' no longer garbled | Verified 8/9 phrasings |
| 05:24 | 05:28 | Route changing stats (population/GDP/net worth) to local search — model's memory is stale (real log: GDP answered as $2.7T) | Verified: stats→local, timeless facts→chat |
| 05:28 | 05:31 | TTS spoken-text sanitizer: markdown/code/URLs/emoji no longer read aloud (Claude & search replies are markdown) | Verified 8 samples, tech tokens preserved |
| 05:31 | 05:39 | Ran a fresh code-audit agent (verified findings by executing code) → fixed 7 real bugs: calc hijacking 'volume 20 percent'→0.2, reminders dropping 'at the store'/'in accounting' context, 'half/quarter of an hour' silently refused, 'quarter past 7' (digit) failing, news dropping 2-char topics ('AI'), weather not falling back to Open-Meteo, postfix '5 factorial' | All 7 verified fixed, 0 regressions |
| 05:39 | 05:52 | Word-numbers (Whisper emits them): new numwords.py + wired into calc ('five plus five'=10), FX ('convert hundred dollars'=100), volume ('set volume to twenty'=20). Scoped so songs/messages stay untouched | Verified + regression-checked |
| 05:15 | 05:52 | Local LoRA fine-tune ran to iter 200 (converged: val loss 2.32→0.012, plateaued by iter 100). Built eval-gate, evaluated base vs adapter-100 vs adapter-200 on held-out novel/broken-English utterances | **KEPT BASE** — adapters overfit: iter100 regressed chat-negatives + confused tools (open→play); iter200 broke local-first (sent search→Claude) + hallucinated a `create_folder` tool. Base: 79%, chat 6/6, all search cases correct. Eval-gate worked as designed |
| 05:52 | 05:54 | Restarted Sheru on the base model with all tonight's fixes live | App RUNNING, models warm 4.4s |
| 05:54 | 05:56 | **Cleanup after testing** (as you asked): my router tests had actually executed side effects — reset system volume 100%→8% (a "make it loud" test cranked it) and cleared 11 stale test reminders (one would've rung a bell at 5pm). Verified clean restart: no restored reminders, no audio errors | System left tidy, volume 8% |
| 05:56 | 06:02 | Wrote tests/test_overnight_fixes.py — 36 side-effect-free regression checks locking in tonight's fixes (mocks all actions so it never changes volume/schedules reminders) | All 36 pass, 0 side effects |
| 06:19 | 06:32 | Scanned the full actions.log for FAIL entries: fixed 'open a wikipedia page on X' (was trying to open an app) → now opens the Wikipedia page; verified the refusal→local-search fix catches the other two ("I can't browse", financial-advice deflection) | All logged FAILs addressed |
