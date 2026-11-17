"""CLI - Display formatting for AIPass.

The one import door: other branches write `from aipass.cli import <name>`. `display` is the module itself.
Names load on first access (PEP 562): an eager import here puts kin in every stack and opens the handlers fence.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aipass.cli.apps.modules import display
    from aipass.cli.apps.modules.display import console, err_console, header, success, error, warning, fatal, section
    from aipass.cli.apps.modules.display import escape, mark_command_failed, command_failed, reset_command_state
    from aipass.cli.apps.modules.display import resolve_exit
    from aipass.cli.apps.modules.templates import operation_start, operation_complete

_DISPLAY = "aipass.cli.apps.modules.display"
_TEMPLATES = "aipass.cli.apps.modules.templates"
_HOMES = {
    **dict.fromkeys(
        (
            "console",
            "err_console",
            "header",
            "success",
            "error",
            "warning",
            "fatal",
            "section",
            "escape",
            "mark_command_failed",
            "command_failed",
            "reset_command_state",
            "resolve_exit",
        ),
        _DISPLAY,
    ),
    **dict.fromkeys(("operation_start", "operation_complete"), _TEMPLATES),
}

__all__ = ["display", *_HOMES]


def __getattr__(name: str):
    """Load a door name on first access and cache it on the package."""
    if name == "display":
        value = importlib.import_module(_DISPLAY)
    elif name in _HOMES:
        value = getattr(importlib.import_module(_HOMES[name]), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
