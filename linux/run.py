"""Start Fatima Voice Studio on Linux: applies the compatibility layer, then runs the normal entry point.

  python linux/run.py                 console mode, opens the browser
  python linux/run.py --no-browser    don't open the browser
  python linux/run.py --tray          also show a tray icon (needs a tray / AppIndicator in your desktop)
  python linux/run.py --check         import everything and exit 0 (works without a display; the tray is optional)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compat  # noqa: E402

compat.apply()

if "--tray" in sys.argv[1:]:
    from studio import app as _app  # noqa: F401  (imports first: tray needs the patched autostart)
    try:
        compat.patch_tray()
    except Exception as e:
        # pystray fails at import time when the desktop has no usable tray (e.g. COSMIC without the AppIndicator
        # typelib). Start without the icon instead of not at all: the menu entry would do nothing otherwise.
        print(f"note: no tray icon ({type(e).__name__}: {e}); starting without it. Quit with "
              f"'{Path(__file__).resolve().parent / 'fatima-voice-studio'} --stop'.", file=sys.stderr)
        compat.notify_no_tray()
        sys.argv = [a for a in sys.argv if a != "--tray"]

if "--check" in sys.argv[1:]:
    # studio's own --check imports the tray module, and pystray fails at import time without a display (servers,
    # systemd). The tray is optional here, so a missing display is reported but doesn't fail the check.
    from studio import app as _app, mcp_server  # noqa: F401,E402
    try:
        from studio import tray  # noqa: F401
    except Exception as e:
        print(f"note: no tray backend here ({type(e).__name__}); the app runs without a tray icon", file=sys.stderr)
    sys.exit(0)

from studio.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
