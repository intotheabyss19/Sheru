# Sheru — Autonomous stress-and-fix session (2026-08-28)

Yash away ~2h; continuing to stress-test + fix Sheru. No push/send/system changes. Each batch: change → re-run
`tests/stress_test.py` → log result.

## Baseline at session start
- 217/260 (~83%) on baseline+adversarial corpus. Failures categorized in `STRESS_REPORT.md`.

## Batch 1 — reminders + phrasing gaps
- NEW **reminders** capability (`reminders.py`): "remind me to X in N min / at H" → parses time, schedules a
  spoken reminder, persists to `data/reminders.jsonl`, restores on restart. Grammar rule + handler.
- Phrasing gaps fixed: clipboard ("what did i copy"), time ("do you have the time"), set_location
  ("i just moved to X", "i'm now in X").
- Result: clipboard 4/4, remind 4/4, time 5/5, set_location 8/8. Overall 226/268 (remaining reminder
  "misses" are stale workflow labels — Sheru now does the right thing).

## Batch 2 — corrections + idiom guards
- Correction handling: "no/actually i meant <X>" re-routes X as a fresh command.
- "remember when …" no longer stored as a fact (negative lookahead) → falls to chat/recall.
- set_location idiom guard: "i live in the moment/present/…" no longer sets location.
- Result: 235/273 (86%).

## Batch 3 — targeted routing fixes
- current-info: catches "raining"; no longer fires on song titles ("play the news", "... by <artist>").
- "X dot com" (spoken) → "X.com" → URL rule (e.g. "open reddit dot com").
- quit no longer grabs "all my tabs/apps"; "cancel that actually <X>" → routes X (correction before stop).
- Result: 239/273 (87%). Remaining failures are acceptable label-diffs (stock/news → Claude), inherent
  idioms ("play it cool", "kill it"), and graceful out-of-scope (chat) — documented as accept-in-report.

## Batch 4 — action-layer tests + harness side-effect fix (IMPORTANT)
- Added `tests/test_actions.py`: unit tests for app resolution, reminder time-parsing, location, message arg
  extraction, engine state. All pass.
- **Caught a harness bug that mutated real user state:** `set_location` (→ config.update_profile) and `remind`
  (→ reminders.schedule) weren't mocked, so stress-test runs had changed the saved location to "Gangtok" and
  created persisted reminders. **Restored location to Ravangla, cleared data/reminders.jsonl, and mocked both
  handlers in the harness.** Lesson: any handler with a real side effect must be mocked in stress_test.py.

## Batch 5 — polite-prefix stripping (biggest systemic fix)
- A fresh generalization workflow (106 new cases: daily-use, polite, Hinglish, new adversarial) exposed that
  **polite/indirect prefixes break every anchored grammar rule** ("could you please open spotify", "can you
  search…", "i need you to remind me…", "please remember…").
- Fix: **strip polite/filler prefixes** ("could you", "can you", "please", "would you mind", "i need you to",
  "let's", "hey", "um") and trailing filler ("a bit", "real quick", "for me") in route() preprocessing — so the
  core command reaches the grammar. Also verb variants: "put on X"→play, "crank it up"→volume, "skip"→next,
  "pull up X.com"→url, "switch over to"→switch. Word-number reminder times ("remind me at nine").
- Corpus grew to 319 cases (added the 106 generalization cases).
