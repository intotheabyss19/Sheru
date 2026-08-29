"""Read the on-screen WhatsApp conversation so Sheru can tell you what someone replied.

WhatsApp desktop is Electron (poor accessibility tree), so this screenshots its window and runs Apple's
on-device Vision OCR (local, free — no cloud, no key). Needs Screen Recording permission for the Sheru
process; without it the capture is blank and we say so. Best-effort: good for reading back the latest
messages, not a perfectly structured transcript (it can't always tell sent from received).
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import time
from pathlib import Path


def _window_id() -> int | None:
    """The window number of WhatsApp's main on-screen window, or None if it isn't open."""
    import Quartz
    opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or []:
        if w.get("kCGWindowOwnerName") == "WhatsApp" and int(w.get("kCGWindowLayer", 0)) == 0:
            b = w.get("kCGWindowBounds", {})
            if b.get("Width", 0) > 200 and b.get("Height", 0) > 200:      # the real window, not a helper
                return int(w["kCGWindowNumber"])
    return None


def _capture(winid: int, out: Path) -> bool:
    # -x silent, -o no window shadow, -l<id> just that window (works without bringing it frontmost)
    subprocess.run(["screencapture", "-x", "-o", f"-l{winid}", str(out)], capture_output=True)
    return out.exists() and out.stat().st_size > 1000


def _ocr_lines(img: Path) -> list[str]:
    """Vision OCR -> text lines in top-to-bottom reading order (Vision's origin is bottom-left)."""
    import Quartz
    import Vision
    from Foundation import NSURL
    src = Quartz.CGImageSourceCreateWithURL(NSURL.fileURLWithPath_(str(img)), None)
    if not src:
        return []
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(1)                 # 0=fast, 1=accurate
    req.setUsesLanguageCorrection_(True)
    Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(cg, {}).performRequests_error_([req], None)
    rows = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if cand:
            rows.append((1.0 - obs.boundingBox().origin.y, cand[0].string()))   # smaller = higher on screen
    rows.sort(key=lambda t: t[0])
    return [s for _, s in rows]


# obvious UI chrome to drop from the OCR text
_DROP = re.compile(r"^(?:type a message|search or start a new chat|online|typing…|typing\.\.\.|"
                   r"last seen.*|\d{1,2}:\d{2}(?:\s*[ap]m)?|today|yesterday|encrypted|\W*)$", re.I)


def _clean(lines: list[str]) -> list[str]:
    return [s.strip() for s in lines if s.strip() and not _DROP.match(s.strip()) and len(s.strip()) > 1]


def read_open_chat(max_lines: int = 8, activate: bool = True) -> str:
    """Read back the latest visible messages in the WhatsApp chat that's currently open."""
    if activate:
        subprocess.run(["osascript", "-e", 'tell application "WhatsApp" to activate'], capture_output=True)
        time.sleep(0.8)
    winid = _window_id()
    if winid is None:
        return "I can't find the WhatsApp window — open WhatsApp and the chat you want me to read."
    out = Path(tempfile.mkstemp(suffix=".png")[1])
    try:
        if not _capture(winid, out):
            return ("I couldn't capture the WhatsApp window — grant Screen Recording to Sheru in "
                    "System Settings, Privacy & Security, Screen Recording, then try again.")
        lines = _clean(_ocr_lines(out))
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    if not lines:
        return "The chat looks empty to me, or I couldn't read it clearly."
    return "Here's what I can read: " + " … ".join(lines[-max_lines:])


def read_chat_with(handle: str, max_lines: int = 8) -> str:
    """Open a specific contact's chat, then read it."""
    digits = re.sub(r"\D", "", handle)
    subprocess.run(["open", f"whatsapp://send?phone={digits}"], check=False)
    time.sleep(1.6)                               # let WhatsApp navigate to the chat
    return read_open_chat(max_lines, activate=False)
