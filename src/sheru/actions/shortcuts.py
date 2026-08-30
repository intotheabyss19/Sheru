"""macOS Shortcuts bridge — run any of Yash's Shortcuts by name via the `shortcuts` CLI.

This is the leverage point for system control: a Shortcut can do things that are painful/impossible to script
directly (Set Focus / Do-Not-Disturb, window management, on-device OCR, …), so Sheru borrows them instead of
re-implementing each. Keep helper shortcuts ALERT-FREE and INPUT-FREE — an interactive prompt blocks `shortcuts
run` forever (we cap it with a timeout so Sheru can't hang).
"""
from __future__ import annotations

import subprocess


def list_shortcuts() -> list[str]:
    """Names of the user's shortcuts (empty list if none exist or the CLI is unavailable)."""
    try:
        r = subprocess.run(["shortcuts", "list"], capture_output=True, text=True, timeout=10)
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        return []


def run_shortcut(name: str, text: str | None = None, timeout: float = 25.0) -> str | None:
    """Run a Shortcut by name. `text`, if given, is piped to its stdin (for shortcuts that take input).
    Returns the shortcut's stdout (stripped) on success — possibly "" for a shortcut that prints nothing —
    or None on failure (unknown shortcut, non-zero exit, timeout)."""
    cmd = ["shortcuts", "run", name]
    if text is not None:
        cmd += ["-i", "-", "-o", "-"]
    try:
        r = subprocess.run(cmd, input=(text if text is not None else None),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None                              # a prompt-blocked / slow shortcut — don't hang Sheru
    except Exception:
        return None
    if r.returncode != 0:
        return None                              # unknown shortcut, or the shortcut itself errored
    return (r.stdout or "").strip()


def resolve_name(spoken: str) -> str | None:
    """Fuzzy-match a spoken shortcut name to one that exists (STT spelling wobble). None if nothing close."""
    names = list_shortcuts()
    if not names:
        return None
    low = spoken.strip().lower()
    for n in names:                              # exact, then substring either way
        if n.lower() == low:
            return n
    for n in names:
        if low and (low in n.lower() or n.lower() in low):
            return n
    try:
        from rapidfuzz import process, fuzz
        m = process.extractOne(spoken, names, scorer=fuzz.WRatio)
        if m and m[1] >= 70:
            return m[0]
    except Exception:
        pass
    return None
