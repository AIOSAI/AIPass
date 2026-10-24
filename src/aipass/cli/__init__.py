"""CLI - Display formatting for AIPass.

Names load on first access (PEP 562): an eager import here puts kin in every stack and opens the handlers fence.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aipass.cli.apps.modules.display import console, header, success, error, warning, section, escape

_DISPLAY = "aipass.cli.apps.modules.display"
_LAZY = ("console", "header", "success", "error", "warning", "section", "escape")

__all__ = [*_LAZY]


def __getattr__(name: str):
    """Load a display name on first access and cache it on the package."""
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(_DISPLAY), name)
    globals()[name] = value
    return value
