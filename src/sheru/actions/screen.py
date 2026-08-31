"""Read what's on screen — on-device Apple Vision OCR (local, free; no cloud, no key).

`screencapture` needs **Screen Recording** permission (separate from Accessibility/Mic); without it macOS returns
a blank/desktop-only image, so read_screen() comes back empty and the caller should nudge for that grant.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .whatsapp_read import _clean, _ocr_lines   # reuse the Vision OCR + chrome-cleaning helpers


def read_screen(max_chars: int = 500) -> str:
    """Screenshot the main display, OCR it (top-to-bottom reading order), return cleaned text (trimmed)."""
    tmp = Path(tempfile.mktemp(suffix=".png"))
    try:
        subprocess.run(["screencapture", "-x", "-o", str(tmp)], capture_output=True, timeout=10)
        if not tmp.exists():
            return ""
        lines = _clean(_ocr_lines(tmp))
    except Exception:
        return ""
    finally:
        tmp.unlink(missing_ok=True)
    text = " · ".join(l.strip() for l in lines if l.strip())
    return text[:max_chars]


def understand_screen(question: str | None = None, max_chars: int = 600) -> str:
    """Natural-language screen understanding via the local huihui Qwen3-VL (much richer than raw OCR — it
    describes the app, layout, and buttons). Falls back to OCR text if the VLM isn't available or errors."""
    try:
        from .. import vision
        if vision.available():
            ans = vision.describe_screen(question)
            if ans:
                return ans[:max_chars]
    except Exception:
        pass
    return read_screen(max_chars=max_chars)   # OCR fallback
