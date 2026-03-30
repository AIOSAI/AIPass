# =================== AIPass ====================
# Name: __main__.py
# Description: Entry point for python -m aipass.cli
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
# =============================================

"""Allow running CLI as a module: python -m aipass.cli."""

import sys

from aipass.cli.apps.cli import main

try:
    sys.exit(main())
except KeyboardInterrupt:
    sys.exit(0)
