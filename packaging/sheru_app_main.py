"""py2app entry point for Sheru.app. Runs the same `sheru.main()` the CLI does, but as a PROPER app-bundle
process so macOS identifies it as 'Sheru' (icon + name) in permission prompts / the mic indicator / Activity
Monitor — not 'python3.12'."""
import os
import sys

_src = "/Users/yash/Projects/Sheru/src"          # alias-mode bundle references the source; be explicit anyway
if os.path.isdir(_src) and _src not in sys.path:
    sys.path.insert(0, _src)

from sheru import main

if __name__ == "__main__":
    sys.exit(main())
