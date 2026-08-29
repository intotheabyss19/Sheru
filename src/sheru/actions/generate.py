"""Generative-agent flow: Claude Code writes runnable code to a scratchpad, Sheru offers to run or move it.

General, NOT per-library: the same path handles manim / pandas / numpy / matplotlib / plain scripts. Sheru mints
an exact output path and tells Claude to write a self-contained script there (PEP 723 inline deps), so 'want to
see it?' is just `uv run <path>` (the script previews its own visual / prints its own results) and 'move it to
<dir>' relocates it. Nothing about manim is hardcoded — the model decides the code; Sheru only owns save + run.
"""
from __future__ import annotations

import datetime
import re
import shutil
import subprocess
import sys
from pathlib import Path

SCRATCHPAD = Path.home() / "Projects" / "Sheru-scratchpad"

# "move it to X" targets — friendly spoken names -> real directories
KNOWN_DIRS = {
    "learningphase": Path.home() / "Projects" / "LearningPhase" / "Python",
    "learning phase": Path.home() / "Projects" / "LearningPhase" / "Python",
    "learning": Path.home() / "Projects" / "LearningPhase" / "Python",
    "python": Path.home() / "Projects" / "LearningPhase" / "Python",
    "desktop": Path.home() / "Desktop",
    "documents": Path.home() / "Documents",
    "downloads": Path.home() / "Downloads",
    "projects": Path.home() / "Projects",
}

_DROP = {"a", "an", "the", "of", "to", "for", "me", "please", "claude", "code", "generate", "make",
         "create", "write", "build", "that", "draws", "drawing", "and", "with", "some", "using", "in", "on"}


def _slug(request: str) -> str:
    kept = [w for w in re.findall(r"[a-z0-9]+", request.lower()) if w not in _DROP][:4]
    return "-".join(kept) or "script"


def mint_path(request: str) -> Path:
    """A fresh, dated, human-readable path in the scratchpad: e.g. manim-animation-circle-2026-08-29.py"""
    SCRATCHPAD.mkdir(parents=True, exist_ok=True)
    base = f"{_slug(request)}-{datetime.date.today().isoformat()}"
    p = SCRATCHPAD / f"{base}.py"
    n = 2
    while p.exists():
        p = SCRATCHPAD / f"{base}-{n}.py"
        n += 1
    return p


def build_task(request: str, path: Path) -> str:
    """The Claude Code task: write ONE self-runnable file to exactly `path`, deps declared inline (PEP 723)."""
    return (
        f"Write a COMPLETE, self-contained, runnable Python program that fulfils this request: {request}\n\n"
        f"Write the file to EXACTLY this path (create parent dirs if needed, overwrite if it exists):\n  {path}\n\n"
        "Hard requirements:\n"
        "- Declare third-party dependencies with a PEP 723 inline header at the very top so `uv run <file>` "
        "installs them automatically, e.g.:\n"
        "    # /// script\n"
        '    # dependencies = ["manim"]\n'
        "    # ///\n"
        "- The file must run with `uv run <file>` ALONE, entry logic under `if __name__ == \"__main__\":`.\n"
        "- If it produces a VISUAL, the script must PREVIEW/open it when run. For manim use "
        '`with tempconfig({"preview": True, "quality": "low_quality"}): SceneName().render()`. '
        "For matplotlib call `plt.show()`. For data work (pandas/numpy) print clear labelled results to stdout.\n"
        "- Do NOT run the program yourself. When done, reply with ONE short sentence naming what you built. "
        "The file on disk is the deliverable, not an explanation."
    )


# generative-intent detection (used by the router)
_GEN_VERB = re.compile(r"\b(generate|make|create|write|build|code|animate|plot|draw|simulate|visuali[sz]e|render)\b")
_GEN_NOUN = re.compile(r"\b(manim|animation|animate|script|program|code|plot|chart|graph|figure|simulation|"
                       r"demo|snippet|function|numpy|pandas|matplotlib|dataframe|visuali[sz]ation|algorithm)\b")
_INFO = re.compile(r"\b(summari[sz]e|explain|what'?s|what is|who|when|where|why|translate|define|tell me about)\b")


def looks_generative(task: str) -> bool:
    """True when 'ask claude to …' wants an artifact built (→ save+offer), not an answer spoken back."""
    t = task.lower()
    if _INFO.search(t):
        return False
    return bool(_GEN_VERB.search(t) and _GEN_NOUN.search(t))


def run(path: Path) -> tuple[bool, str]:
    """Run the artifact with `uv run <path>` (installs its inline deps) from its own dir; (ok, short output tail)."""
    p = Path(path)
    if not p.exists():
        return False, "the file isn't there anymore"
    for cmd in (["uv", "run", str(p)], [sys.executable, str(p)]):
        try:
            proc = subprocess.run(cmd, cwd=str(p.parent), capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            continue                                   # uv not installed -> fall through to python
        except subprocess.TimeoutExpired:
            return False, "it took too long, so I stopped it"
        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            err = (proc.stderr or "").strip().splitlines()[-3:]
            return False, (" ".join(err) or "it errored")[-240:]
        tail = out.splitlines()[-4:]
        return True, (" ".join(tail))[-240:]
    return False, "I couldn't find a way to run it"


def resolve_dir(phrase: str) -> Path | None:
    """Map a spoken destination ('LearningPhase', '~/Projects/x') to a real directory, or None if unclear."""
    phrase = (phrase or "").strip().strip("'\"")
    if phrase.startswith(("~", "/")):
        return Path(phrase).expanduser()
    key = re.sub(r"[^a-z0-9 ]", "", phrase.lower()).strip()
    for name, d in KNOWN_DIRS.items():
        if name in key:
            return d
    return None


def move(path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(path).name
    shutil.move(str(path), str(dest))
    return dest
