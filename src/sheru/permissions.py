"""Coherent permission requests for the packaged .app.

Sheru.app is a separate TCC identity from the terminal, so it needs its OWN grants for:
- Accessibility — the F5 hotkey, typing mode, and any synthetic key/mouse events.
- Automation — controlling WhatsApp / System Events (e.g. auto-pressing Send).
macOS grants these per-app in System Settings; this module prompts for them and opens the right pane so Yash
toggles Sheru on ONCE, instead of clicking Send/etc. himself every time.
"""
from __future__ import annotations

import subprocess

_ACCESSIBILITY_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
_AUTOMATION_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"


def accessibility_trusted() -> bool:
    """True if THIS process has Accessibility (hotkey/typing/synthetic events). Assume ok if we can't tell."""
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return True


def request_accessibility(prompt: bool = True) -> None:
    """Trigger the system Accessibility prompt (adds Sheru to the list) and open the pane to toggle it on."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions
        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": bool(prompt)})
    except Exception:
        pass
    subprocess.run(["open", _ACCESSIBILITY_PANE], check=False)


def request_automation() -> None:
    """Trigger the Automation consent prompt via a benign System Events call, then open the pane."""
    subprocess.run(["osascript", "-e", 'tell application "System Events" to get name of first application process'],
                   capture_output=True)
    subprocess.run(["open", _AUTOMATION_PANE], check=False)


def request_all() -> None:
    request_accessibility(prompt=True)
    request_automation()
