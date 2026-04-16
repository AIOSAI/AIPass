# =================== AIPass ====================
# Name: log_level_content.py
# Description: Log Level Hygiene Standards Content
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Log Level Hygiene Standards Content

Provides Rich-formatted reference text for the log level hygiene standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_log_level_standards() -> str:
    """Return Rich-formatted log level hygiene standards text"""
    json_handler.log_operation("standard_content_queried", {"standard": "log_level"})
    return """[bold white]LOG LEVEL HYGIENE STANDARD[/bold white]

[yellow]PURPOSE:[/yellow]
  Ensure ERROR level is reserved for real system failures.
  User input errors must use WARNING level.
  This is critical for Medic v2 push-based error detection accuracy.

[yellow]THE RULES:[/yellow]

  [bold red]ERROR[/bold red] = System failures ONLY
    - Crashes, unhandled exceptions
    - Timeouts, connection failures
    - Import failures, missing dependencies
    - File I/O errors (disk full, permission denied)
    - Internal state corruption

  [bold yellow]WARNING[/bold yellow] = User input errors
    - Unknown command, unrecognized action
    - Invalid arguments, bad syntax
    - Missing required arguments
    - Typos in user input
    - Command routing failures (no module handled)

  [bold cyan]INFO[/bold cyan] = Normal operations
    - Successful completions
    - Module discoveries
    - Configuration loaded
    - Service started/stopped

[yellow]EXAMPLES:[/yellow]

  [red]BAD:[/red]
    # [WRONG] Use ERROR for unknown user commands
    # [WRONG] Use ERROR when no module handled the command
    # [WRONG] Use ERROR for invalid user arguments

  [green]GOOD:[/green]
    # [CORRECT] log as WARNING: "Unknown command: {command}"
    # [CORRECT] log as WARNING: "No module handled command: {args.command}"
    # [CORRECT] log as WARNING: "Invalid argument: {arg}"
    # [CORRECT] log as ERROR: "Failed to connect to database: {e}"
    # [CORRECT] log as ERROR: "Import failed: {e}"

[yellow]WHY THIS MATTERS:[/yellow]
  Medic v2 monitors ERROR-level log entries to detect real system issues.
  If user typos trigger ERROR, Medic sees noise instead of signal.
  Clean log levels = accurate error detection = healthier system."""
