# =================== AIPass ====================
# Name: log_handler_content.py
# Description: Log Handler Standards Content
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
Log Handler Standards Content

Provides Rich-formatted reference text for the log handler rotation standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_log_handler_standards() -> str:
    """Return Rich-formatted log handler standards text"""
    json_handler.log_operation("standard_content_queried", {"standard": "log_handler"})
    return """[bold white]LOG HANDLER ROTATION STANDARD[/bold white]

[yellow]PURPOSE:[/yellow]
  All logging MUST use RotatingFileHandler via prax system_logger.
  Raw logging.FileHandler and logging.StreamHandler cause unbounded
  log growth that can crash the entire AIPass command infrastructure.

[yellow]THE RULES:[/yellow]

  [bold red]PROHIBITED[/bold red]
    - Plain FileHandler (no rotation, unbounded growth)
    - Plain StreamHandler alongside file-based log output
    - Any handler setup writing to system_logs/ without rotation

  [bold green]REQUIRED[/bold green]
    - Import prax system_logger (centralized rotating handler)
    - All log output via system_logger methods (info/warning/error)
    - Prax handles rotation automatically (maxBytes + backupCount)

  [bold cyan]EXEMPT[/bold cyan]
    - Prax's own logging infrastructure (it IS the implementation)
    - Test files that set up temporary loggers for testing purposes

[yellow]EXAMPLES:[/yellow]

  [red]BAD:[/red]
    # [WRONG] Plain file handler with no rotation — grows forever
    # [WRONG] Plain stream handler alongside file-based log output
    # [WRONG] Custom handler setup bypassing prax entirely

  [green]GOOD:[/green]
    # [CORRECT] Import and use prax system_logger (has rotation built in)
    # [CORRECT] All output via system_logger info/warning/error methods
    # [CORRECT] If custom handler needed, use RotatingFileHandler with limits

[yellow]WHY THIS MATTERS:[/yellow]
  On 2026-02-26, telegram bots using plain FileHandler accumulated
  181,566 log lines (~100K ERROR lines) that crashed ALL drone commands.
  The error catchup scanner tried to process 100K errors, hit Python's
  recursion limit, and cascaded into system-wide failure.
  RotatingFileHandler prevents this by capping file size automatically."""
