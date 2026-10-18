# =================== AIPass ====================
# Name: cli.py
# Description: Drone CLI entry point — console_scripts wrapper
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""
Drone CLI — command-line interface for aipass.drone.
"""

import os
import sys

# Windows consoles default to cp1252, which cannot encode Rich's Unicode (UnicodeEncodeError). PYTHONUTF8
# reaches only child interpreters, so this process's open streams are reconfigured in place, before Rich imports.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")  # for child subprocesses
    for _stream in (sys.stdout, sys.stderr):
        # A capture layer (pytest) or a non-TextIOWrapper stream has no reconfigure.
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.drone.apps.drone import main as _drone_main


def main() -> None:
    """Entry point for the `drone` CLI command."""
    sys.exit(_drone_main())


if __name__ == "__main__":
    main()
