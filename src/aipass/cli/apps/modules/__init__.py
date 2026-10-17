"""
CLI Public API - Services Exported to Other Branches"""

from aipass.cli.apps.modules.display import console, err_console

from aipass.cli.apps.modules.display import header, success, error, warning, fatal, section

# header/success/section/templates parse markup, error/warning/fatal do not: escape values with brackets
from aipass.cli.apps.modules.display import escape

from aipass.cli.apps.modules.display import mark_command_failed, command_failed, reset_command_state, resolve_exit

from aipass.cli.apps.modules.templates import operation_start, operation_complete

__all__ = [
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
    "operation_start",
    "operation_complete",
]
