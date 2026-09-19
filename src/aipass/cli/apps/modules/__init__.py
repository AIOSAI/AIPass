"""
CLI Public API - Services Exported to Other Branches

Import these in your branch modules:
    # Rich console (lowercase service instance pattern)
    from aipass.cli.apps.modules import console
    console.print("message")  # Rich formatted output

    # Display functions
    from aipass.cli.apps.modules import header, success, error, warning

    # Operation templates
    from aipass.cli.apps.modules import operation_start, operation_complete

    # A value that may carry square brackets, into a markup-parsing function
    from aipass.cli.apps.modules import escape
    success(escape(value))

PATTERN (from Prax):
- This directory contains PUBLIC API
- apps/handlers/ contains PRIVATE implementation
- Modules are thin wrappers exposing clean interfaces
- CLI provides display services to all branches
- Lowercase 'console' follows service instance pattern (like 'logger')
"""

# Rich console (primary service - like Prax logger)
from aipass.cli.apps.modules.display import console, err_console

# Display functions
from aipass.cli.apps.modules.display import header, success, error, warning, fatal, section

# Literal brackets — header/success/section/templates parse markup, error/warning/fatal do not
from aipass.cli.apps.modules.display import escape

# Exit-code failure-flag API
from aipass.cli.apps.modules.display import mark_command_failed, command_failed, reset_command_state, resolve_exit

# Operation templates
from aipass.cli.apps.modules.templates import operation_start, operation_complete

__all__ = [
    # Rich console (primary service)
    "console",
    "err_console",
    # Display
    "header",
    "success",
    "error",
    "warning",
    "fatal",
    "section",
    # Literal brackets
    "escape",
    # Exit-code failure-flag API
    "mark_command_failed",
    "command_failed",
    "reset_command_state",
    "resolve_exit",
    # Templates
    "operation_start",
    "operation_complete",
]
