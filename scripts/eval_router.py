#!/usr/bin/env python3
"""Phase 4 — eval-gate for the fine-tuned router. Runs a held-out battery of realistic + broken-English
utterances through the local model's decide() and scores tool-choice accuracy, so we ONLY deploy the LoRA
adapter if it beats the base model (and doesn't regress chit-chat).

Usage:
  uv run python scripts/eval_router.py                          # base model
  uv run python scripts/eval_router.py --adapter data/finetune/adapter   # base + adapter
Run both, compare the two accuracies. Deploy the adapter only if it is strictly better with no chat regression.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# (utterance, {acceptable tool names})  —  "say" means: answer in chat, do NOT call a tool.
# web_search/look_up are interchangeable (both are "search the web"); ask_claude is for real coding/multi-step work.
SEARCH = {"web_search", "look_up"}
BATTERY = [
    # apps
    ("open spotify", {"open_app"}), ("can you open whatsapp please", {"open_app"}),
    ("launch the discord app", {"open_app"}), ("switch to obsidian", {"open_app"}),
    ("close spotify", {"quit_app"}), ("quit the discord now", {"quit_app"}),
    # music
    ("play tum hi ho", {"play_song"}), ("put on some arijit singh", {"play_song"}),
    ("play despacito on spotify", {"play_song"}), ("pause the music", {"media"}),
    ("next song", {"media"}),
    # volume / timer
    ("set volume to 40", {"set_volume"}), ("turn the volume up", {"set_volume"}),
    ("set a timer for 5 minutes", {"set_timer"}), ("timer for ten minute", {"set_timer"}),
    # search / current-info (should NOT be ask_claude)
    ("what is the news today", SEARCH), ("who won the cricket match", SEARCH),
    ("how much is 100 dollars in rupees", SEARCH), ("whats the weather in delhi", SEARCH),
    ("search for the best pizza near me", SEARCH), ("look up the price of bitcoin", SEARCH),
    ("who is the prime minister of japan right now", SEARCH),
    # images
    ("show me pictures of cats", {"image_search"}), ("images of the golden gate bridge", {"image_search"}),
    # messaging
    ("message piyush that i am running late", {"draft_message"}),
    ("text mom i will call her later", {"draft_message"}),
    # remember / address
    ("remember my wifi password is on the fridge", {"remember"}),
    ("address gaurav as boss in messages", {"set_address"}),
    # real Claude work (coding / files / multi-step)
    ("write a python script to rename my files", {"ask_claude"}),
    ("fix the bug in my project", {"ask_claude"}),
    ("make a numpy plot of a sine wave", {"ask_claude"}),
    ("create a folder called invoices on my desktop", {"ask_claude"}),
    # chit-chat / factual answers — should stay in chat, NO tool
    ("who are you", {"say"}), ("tell me a joke", {"say"}), ("thank you so much", {"say"}),
    ("good night sheru", {"say"}), ("how are you doing", {"say"}),
    ("what is the capital of france", {"say"}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default=None, help="LoRA adapter dir to serve on top of the base model")
    args = ap.parse_args()

    import warnings
    warnings.filterwarnings("ignore")
    from sheru.llm_local import LocalLLM
    from sheru import config

    llm = LocalLLM(config.LOCAL_LLM, adapter_path=args.adapter)
    llm.load()
    tag = f"adapter={args.adapter}" if args.adapter else "BASE (no adapter)"
    print(f"\n=== eval: {tag} ===")

    ok = 0
    chat_ok = chat_n = 0
    misses = []
    for utt, want in BATTERY:
        d = llm.decide(utt)
        got = d.get("tool") if d.get("tool") else "say"
        hit = got in want
        ok += hit
        if want == {"say"}:
            chat_n += 1
            chat_ok += hit
        if not hit:
            misses.append((utt, sorted(want), got))
    n = len(BATTERY)
    print(f"  overall:  {ok}/{n}  = {ok/n:.0%}")
    print(f"  chat-neg: {chat_ok}/{chat_n}  (must not regress — tool-calling on plain chat is bad)")
    if misses:
        print("  misses:")
        for utt, want, got in misses:
            print(f"    {utt:46} want {want}  got [{got}]")
    print(f"SCORE {ok} {n} {chat_ok} {chat_n}")


if __name__ == "__main__":
    main()
