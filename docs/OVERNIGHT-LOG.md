# Overnight work log — for Yash (waking ~9am)

Autonomous session: improve Sheru + GUI, add personality, fix issues, test, research, fine-tune.
Times are local. Newest at the bottom.

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
