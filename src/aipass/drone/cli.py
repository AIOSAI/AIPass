# =================== AIPass ====================
# Name: cli.py
# Description: Drone CLI entry point — console_scripts wrapper
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-11-14
# =============================================

"""
Drone CLI — command-line interface for aipass.drone.
"""

import sys

from aipass.drone.apps.drone import main as _drone_main


def main() -> None:
    """Entry point for the `drone` CLI command."""
    sys.exit(_drone_main())


if __name__ == "__main__":
    main()
