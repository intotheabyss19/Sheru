"""Standalone harness: show the Sheru chat panel with sample turns so it can be screenshotted for GUI iteration.
Runs its own NSApplication; nothing routes for real. Kill the process after capturing."""
import sys, time, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, "/Users/yash/Projects/Sheru/src")

from AppKit import NSApplication
from PyObjCTools import AppHelper
from sheru import panel

app = NSApplication.sharedApplication()
app.setActivationPolicy_(0)   # regular, so the panel shows

tp = panel.TypePanel.alloc().initWithSubmit_(lambda t, sink: None)
now = time.time()
tp._chat = [
    {"role": "you", "text": "what's the weather", "ts": now - 600},
    {"role": "sheru", "text": "It's 26° in Bhubaneswar right now, thunderstorms. Today's high is 28, low 25.",
     "src": "local", "ts": now - 599},
    {"role": "you", "text": "convert 100 dollars to rupees", "ts": now - 400},
    {"role": "sheru", "text": "100 US dollars is about 9,539 rupees.", "src": "local", "ts": now - 399},
    {"role": "you", "text": "write a python script to rename my files", "ts": now - 200},
    {"role": "sheru", "text": "On it — I'll drop a rename script in your scratchpad and walk you through running it.",
     "src": "claude", "ts": now - 199},
    {"role": "you", "text": "what is the square root of 5", "ts": now - 60},
    {"role": "sheru", "text": "That's 2.236068.", "src": "local", "ts": now - 59},
    {"role": "you", "text": "who is Ada Lovelace", "ts": now - 20},
    {"role": "sheru", "text": "", "pending": True, "src": "local", "ts": now - 2},
]
tp.show()
# animate the pending dots a little
tp._sw_start()
AppHelper.runEventLoop()
