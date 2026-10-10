"""Start Fatima Voice Studio on macOS: applies the compatibility layer, then runs the normal entry point.

  python macos/run.py                 console mode, opens the browser
  python macos/run.py --no-browser    don't open the browser
  python macos/run.py --tray          also show a tray icon (needs pyobjc-framework-Cocoa)
  python macos/run.py --check         import everything and exit 0
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compat  # noqa: E402

compat.apply()

if "--tray" in sys.argv[1:]:
    from studio import app as _app  # noqa: F401  (imports first: tray needs the patched autostart)
    compat.patch_tray()

if "--check" in sys.argv[1:]:
    from studio import app as _app, mcp_server  # noqa: F401,E402
    try:
        from studio import tray  # noqa: F401
    except Exception as e:
        print(f"note: no tray backend here ({type(e).__name__}); the app runs without a tray icon", file=sys.stderr)
    sys.exit(0)

from studio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
