"""Self-improvement bridge: on the user's EXPLICIT request, open a Claude Code "trainer" session on Sheru's
own codebase so Claude can diagnose + fix Sheru's behaviour. Writes a context brief (recent journal + logs +
the issue) and launches interactive `claude --continue` in the repo, so the trainer keeps this session's context.
"""
from __future__ import annotations

from pathlib import Path

from .. import claude_code, config

ROOT = Path(__file__).resolve().parents[3]      # ~/Projects/Sheru


def _tail(p: Path, n: int) -> str:
    try:
        return "\n".join(p.read_text().splitlines()[-n:]) or "(empty)"
    except Exception:
        return "(none)"


def open_trainer(issue: str = "") -> str:
    """Write a context brief and open the trainer session. `issue` = the part the user asked to fix (optional)."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    brief = config.DATA_DIR / "trainer_brief.md"
    brief.write_text(
        "# Sheru trainer brief\n\n"
        f"Yash asked Sheru to have you fix this behaviour:\n\n> {issue or '(unspecified — diagnose from the recent journal/logs below)'}\n\n"
        f"You are Sheru's trainer (Claude Code) working in `{ROOT}`. Please:\n"
        "1. Reproduce/diagnose from the code plus the context below — say plainly **what's actually broken vs. what works**.\n"
        "2. Make a surgical fix, then restart the app to verify: `pkill -f .venv/bin/sheru; (.venv/bin/sheru &)`.\n"
        "3. Tell Yash in plain terms what the error was, what you fixed, and anything that can't be fixed here.\n\n"
        "## Recent journal (utterance → routing/speech)\n```\n"
        + _tail(config.DATA_DIR / "journal.jsonl", 25) + "\n```\n\n"
        "## Recent app log\n```\n" + _tail(config.DATA_DIR / "sheru.log", 40) + "\n```\n"
    )
    # first-person message Sheru "types" into the trainer session
    prompt = (
        f"Hi trainer, I'm Sheru. Yash has found a problem with my behaviour and wants you to fix it: "
        f"{issue or '(see my recent journal/logs)'}. I've written the details plus my recent journal and logs to "
        "data/trainer_brief.md — please read that first, work out what's actually broken versus what's fine, fix it "
        "in my code, restart me to verify, and then tell Yash plainly what the error was and what you fixed."
    )
    claude_code.open_interactive(prompt, ROOT, resume=True)
    return "Opening a session with my trainer, Claude — I'll hand over what Yash wants fixed. Watch the terminal."
