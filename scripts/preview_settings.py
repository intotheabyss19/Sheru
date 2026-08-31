"""Render the Settings window OFF-SCREEN to a PNG (in-memory bitmap of the view only) for layout iteration.

Privacy: this NEVER screencaptures the display and never puts a window on screen — it builds the view hierarchy
and renders just that view to a bitmap. Safe to run while the user is doing something else.

Usage: python scripts/preview_settings.py <out.png>
"""
import sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/Users/yash/Projects/Sheru/src")

from AppKit import NSApplication, NSBitmapImageFileTypePNG
from sheru.settings import Settings

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/settings_preview.png"


class _Speaker:
    def speak(self, t):
        pass


class MockApp:
    speaker = _Speaker()
    _cue_paths = None

    def _ensure_orb(self):
        pass


app = NSApplication.sharedApplication()
app.setActivationPolicy_(2)   # prohibited — no dock, no window ever shown on screen
s = Settings.alloc().initWithApp_(MockApp())
s._build()                    # builds the window + view hierarchy but does NOT order it on screen
view = s._view
view.window().layoutIfNeeded() if hasattr(view.window(), "layoutIfNeeded") else None
rect = view.bounds()
rep = view.bitmapImageRepForCachingDisplayInRect_(rect)
view.cacheDisplayInRect_toBitmapImageRep_(rect, rep)
data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
ok = bool(data and data.writeToFile_atomically_(OUT, True))
print("wrote" if ok else "FAILED", OUT, "size", rect.size.width, "x", rect.size.height)
