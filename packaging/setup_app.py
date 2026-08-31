"""Build Sheru.app as a PROPER app bundle (py2app, ALIAS mode) so the running process is identified as 'Sheru'
with the app icon — in permission dialogs, the orange mic-in-use dot, and Activity Monitor — instead of the bare
'python3.12' interpreter.

Alias mode (`-A`) references the existing venv + source (it does NOT re-bundle the heavy MLX/pyobjc deps), so the
build is fast and small; the bundle is machine-specific (fine — this is Yash's Mac). No LSUIElement in the plist:
the app already demotes itself to Accessory at runtime (app._hide_dock), which hides the dock icon WITHOUT the
faceless-status-item collapse that Info.plist LSUIElement caused with the old shim.

Build:  .venv/bin/python packaging/setup_app.py py2app -A --dist-dir dist
"""
import os

from setuptools import setup

HERE = os.path.dirname(os.path.abspath(__file__))

setup(
    name="Sheru",
    app=[os.path.join(HERE, "sheru_app_main.py")],
    options={
        "py2app": {
            "iconfile": os.path.join(HERE, "AppIcon.icns"),
            "plist": {
                "CFBundleName": "Sheru",
                "CFBundleDisplayName": "Sheru",
                "CFBundleIdentifier": "com.sheru.assistant",
                "CFBundleShortVersionString": "0.1.0",
                "CFBundleVersion": "0.1.0",
                "LSMinimumSystemVersion": "13.0",
                "NSMicrophoneUsageDescription": "Sheru listens for your voice commands.",
                "NSSpeechRecognitionUsageDescription": "Sheru transcribes your voice commands.",
                "NSAppleEventsUsageDescription": "Sheru controls apps like Spotify and WhatsApp on your behalf.",
            },
        }
    },
)
