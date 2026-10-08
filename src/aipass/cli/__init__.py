"""CLI - Display formatting for AIPass.

The display names below load on first attribute access (PEP 562), not at
package import: an eager import here ran apps/modules/display, and through it
this branch's handlers, on behalf of whoever imported aipass.cli first, so a
foreign importer of the handlers always found kin already standing in the
stack (DPLAN-0404). `from aipass.cli import console` works as before.
"""

import importlib
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aipass.cli.apps.modules.display import console, header, success, error, warning, section, escape

_DISPLAY = "aipass.cli.apps.modules.display"
_LAZY = ("console", "header", "success", "error", "warning", "section", "escape")

__all__ = [*_LAZY, "cli_entry"]


def __getattr__(name: str):
    """Load a display name on first access and cache it on the package."""
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(_DISPLAY), name)
    globals()[name] = value
    return value


def cli_entry():
    """Console_scripts entry point for the `aipass` command."""
    from aipass.cli.apps.cli import main

    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
