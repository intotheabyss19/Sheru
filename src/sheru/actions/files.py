"""Safe local filesystem actions: make a folder, create a file, open a terminal in a directory.

No AI, no shell string interpolation — names are sanitised to a single path component and everything is
created strictly under the user's home tree, so a misheard command can never escape to `/` or `..`.
This exists because the local model used to *guess* ("Opening Finder") for "make a folder called X".
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

HOME = Path.home()

# spoken location word -> base directory (default: home)
_BASES = {
    "home": HOME, "home directory": HOME, "here": HOME,
    "desktop": HOME / "Desktop", "the desktop": HOME / "Desktop",
    "documents": HOME / "Documents", "downloads": HOME / "Downloads",
    "projects": HOME / "Projects",
}


def _base_for(where: str | None) -> Path:
    if not where:
        return HOME
    w = where.strip().lower().rstrip(".")
    if w in _BASES:
        return _BASES[w]
    # "the X folder" / "my X folder" -> HOME/X if it exists, else home
    w = re.sub(r"^(?:my|the)\s+", "", w)
    w = re.sub(r"\s+(?:folder|directory|dir)$", "", w).strip()
    cand = HOME / w.title() if w else HOME
    return cand if cand.is_dir() else HOME


def _clean_name(name: str) -> str:
    """One safe path component: drop directory separators, quotes, trailing punctuation, and any '..'."""
    n = name.strip().strip("\"'").rstrip(".")
    n = n.replace("/", " ").replace("\\", " ").replace("..", "")
    n = re.sub(r"\s+", " ", n).strip()
    return n


def make(remainder: str) -> str:
    """Handle 'folder/file <name> [in <where>]'. `remainder` starts at 'folder'/'file'/'directory'/etc."""
    r = remainder.strip()
    is_file = bool(re.search(r"\b(file|document)\b|\.txt|\.md", r))
    # location: "in/on/under/inside <where>"
    mloc = re.search(r"\b(?:in|on|under|inside|to|at)\s+(?:my\s+|the\s+)?(.+?)\s*$", r)
    where = mloc.group(1) if mloc else None
    # name: "called/named <X>" wins; else strip type + location words and take what's left
    mname = re.search(r"(?:called|named|titled?)\s+(.+?)(?:\s+(?:in|on|under|inside|to|at)\s+.+)?$", r)
    if mname:
        name = mname.group(1)
    else:
        name = re.sub(r"^\s*(?:folder|directory|dir|file|text\s+file|txt\s+file|document)\s+", "", r)
        name = re.sub(r"\s+(?:in|on|under|inside|to|at)\s+.+$", "", name)
    # if the location got swept into the name (no explicit 'called'), re-split
    if not mloc:
        where = None
    name = _clean_name(name)
    if not name:
        return "What should I name it?"
    if is_file and not re.search(r"\.\w{1,5}$", name):
        name += ".txt"
    base = _base_for(where)
    target = base / name
    try:
        base.mkdir(parents=True, exist_ok=True)
        if is_file:
            if target.exists():
                return f"{name} already exists in {base.name or 'home'}."
            target.touch()
            return f"Created the file {name} in {base.name or 'your home folder'}."
        target.mkdir(parents=True, exist_ok=True)
        return f"Made the folder {name} in {base.name or 'your home folder'}."
    except Exception as e:
        return f"I couldn't create {name}: {e}"


def open_terminal(where: str | None) -> str:
    """Open a Ghostty terminal window already cd'd into a directory under home."""
    base = _base_for(where)
    subprocess.Popen(["open", "-na", "Ghostty", "--args",
                      "--window-save-state=never", f"--working-directory={base}"])
    return f"Opened a terminal in {base.name or 'your home folder'}."
