# Sheru — Stress Test Report (2026-08-28)

260 routing cases (46 hand-written baseline + 214 workflow-generated, 126 adversarial) run through the real
router + local 4B (actions mocked). Reproduce: `uv run python tests/stress_test.py`.

## Headline
- **Baseline corpus: 46/46 (100%).**
- **Full incl. adversarial: 217/260 (~83%).** Of the 43 "failures," ~10 are *acceptable* label-disagreements
  (see §0), so the effective correct rate is **~87%**, and the genuinely-broken cases are **~25**, almost all
  edge idioms or missing features — not core commands.

## Fixed by this stress test (were real bugs)
- **Current-info now delegates to Claude** (the biggest cluster, ~18 cases): news, headlines, stock/crypto
  prices, sports scores, "is it raining", elections, "who's the PM" — the 4B was *answering from stale memory*;
  added a Tier-0 current-info grammar rule → Claude.
- **`switch to duckduckgo`** set the engine instead of trying to open a "duckduckgo" app (reordered set-engine
  before switch-app).
- **`go to https://…`** now opens the URL (regex accepts the `https://` prefix).
- **`what's on my clipboard`** now matches (clipboard grammar broadened).
- **`write a python script…`** now delegates to Claude (coding grammar).
- **`search for pictures of X`** now routes to images.

## §0 Acceptable "failures" (routing is fine, just labeled differently) — no action
`google bitcoin price`, `look up tesla stock price`, `find the latest news`, `find out who the PM is` → all go
to **Claude** (labeled "search"). Claude fetching live data is *better* than opening a browser tab. Leave as-is.

## Remaining real weak spots — for you to prioritize

### 1. Grammar over-triggers on idioms (~10) — inherent tension
Greedy verbs catch figures of speech:
- `play it cool` → play_song · `kill it` → quit · `go to sleep` → switch · `open up to me` → open_app
- `remember when we went to goa` → store-fact · `i live in the moment` → set-location
- **Recommendation:** these are near-impossible to fix in pure regex without breaking real commands
  (`play <song>`, `remember <fact>`). Best handled by letting the **local LLM disambiguate** ambiguous
  single-verb phrases instead of a hard grammar match, or add a tiny negative-guard list for the worst idioms.
  Low priority (rare in real use).

### 2. Missing capabilities → misroute instead of graceful "can't" (~8)
- `remind me to call mom at five` → inconsistent (timer/remember/chat) — **no reminder feature.**
- `turn on the lights` → volume · `close all my tabs` / `close all my apps` → quit · `look up my calendar` →
  search · `order me a pizza` / `book me a flight` → chat.
- **Recommendation:** add a **reminders** capability (calendar/notification), and a catch for clearly
  out-of-scope requests → either delegate to Claude (flights/pizza via Claude-in-Chrome later) or say
  "I can't do that yet" instead of a wrong action. Medium priority — reminders is a real want.

### 3. Correction handling (~2)
- `no wait i meant firefox not chrome` · `cancel that actually search for pizza recipes` → not understood.
- **Recommendation:** treat "no/actually/i meant …" as a correction of the last turn (partly built via the
  pending-confirmation flow; extend it to general corrections). Medium priority.

### 4. Minor phrasing gaps (~5)
- `what did i copy` (clipboard) · `do you have the time` (time) · `i just moved to gangtok` (set-location) ·
  `set a timer` (no duration → should ask) · `spotify` bare (→ open Spotify?).
- **Recommendation:** broaden these grammar patterns; ask for the missing arg when a required one is absent.
  Low-medium, quick wins.

## Not tested here (see `tests/MANUAL_TESTS.md`)
STT accuracy on real speech, the GUI/panel, F5 activation, real side-effecting actions, message send, and
memory-across-restart — all require a human. The harness only covers **routing** (which utterance → which
action), with actions mocked.
