"""CLI - Display formatting for AIPass.

The import door, `from aipass.cli import <name>`; `display` is the module. Read on access (PEP 562):
an eager import puts kin in every stack and opens the handlers fence.
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
    """Hand out a door name from its home on each access."""
    # Never cached on the package: a patch on the home must reach every caller reading through here.
    if name == "display":
        return importlib.import_module(_DISPLAY)
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been read yet."""
    return sorted(set(globals()) | set(__all__))
