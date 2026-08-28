"""TCC permission probes + a Siri-style onboarding wizard.

Probes are READ-ONLY (they query authorization status; they do not force changes). The wizard opens the
correct System Settings pane for anything missing and can trigger the OS prompt where an API allows it.
Sheru needs, like Siri: Microphone (listen), Accessibility (control UI / global hotkey), Automation /
Apple Events (drive apps via AppleScript), Screen Recording (see the screen).
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

# --- pyobjc backends (all optional; probes degrade to "unknown" if unavailable) ---
try:
    from AVFoundation import AVCaptureDevice, AVMediaTypeAudio
except Exception:
    AVCaptureDevice = None
try:
    from Quartz import CGPreflightScreenCaptureAccess, CGRequestScreenCaptureAccess
except Exception:
    CGPreflightScreenCaptureAccess = None
try:
    from ApplicationServices import AXIsProcessTrusted
except Exception:
    try:
        from HIServices import AXIsProcessTrusted
    except Exception:
        AXIsProcessTrusted = None
try:
    from ApplicationServices import AXIsProcessTrustedWithOptions
    from CoreFoundation import CFDictionaryCreate, kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks
except Exception:
    AXIsProcessTrustedWithOptions = None

# System Settings > Privacy & Security deep links
_PANES = {
    "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "screen": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "siri": "x-apple.systempreferences:com.apple.Siri-Settings.extension",
    "keyboard_shortcuts": "x-apple.systempreferences:com.apple.preference.keyboard?Shortcuts",
}

_MIC_STATUS = {0: "not-determined", 1: "restricted", 2: "denied", 3: "granted"}


@dataclass
class Perm:
    key: str
    label: str
    why: str
    status: str          # granted | denied | not-determined | unknown
    pane: str


def _mic() -> str:
    if AVCaptureDevice is None:
        return "unknown"
    return _MIC_STATUS.get(AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio), "unknown")


def _screen() -> str:
    if CGPreflightScreenCaptureAccess is None:
        return "unknown"
    return "granted" if CGPreflightScreenCaptureAccess() else "denied"


def _accessibility() -> str:
    if AXIsProcessTrusted is None:
        return "unknown"
    return "granted" if AXIsProcessTrusted() else "denied"


def _automation() -> str:
    """Probe Apple Events access by asking System Events for a trivial value; -1743 = not authorized."""
    r = subprocess.run(["osascript", "-e",
                        'tell application "System Events" to return name of first process'],
                       capture_output=True, text=True, timeout=8)
    if r.returncode == 0:
        return "granted"
    if "-1743" in r.stderr or "Not authorized" in r.stderr or "-600" in r.stderr:
        return "denied"
    return "unknown"


def status() -> list[Perm]:
    return [
        Perm("microphone", "Microphone", "so Sheru can hear you", _mic(), _PANES["microphone"]),
        Perm("accessibility", "Accessibility", "so Sheru can use a hotkey and control other apps' UI",
             _accessibility(), _PANES["accessibility"]),
        Perm("automation", "Automation", "so Sheru can drive apps (open, switch, play music) via AppleScript",
             _automation(), _PANES["automation"]),
        Perm("screen", "Screen Recording", "so Sheru can read what's on your screen", _screen(), _PANES["screen"]),
    ]


def open_pane(key: str) -> None:
    subprocess.run(["open", _PANES.get(key, _PANES["microphone"])], check=False)


def request_prompt(key: str) -> None:
    """Trigger the OS prompt where an API allows it (else the pane is the only route)."""
    if key == "microphone" and AVCaptureDevice is not None:
        AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeAudio, lambda ok: None)
    elif key == "screen" and CGPreflightScreenCaptureAccess is not None:
        CGRequestScreenCaptureAccess()
    elif key == "accessibility" and AXIsProcessTrusted is not None:
        opts = CFDictionaryCreate(None, ["AXTrustedCheckOptionPrompt"], [True], 1,
                                  kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks)
        AXIsProcessTrustedWithOptions(opts)
    else:
        open_pane(key)


def all_granted() -> bool:
    return all(p.status == "granted" for p in status())
