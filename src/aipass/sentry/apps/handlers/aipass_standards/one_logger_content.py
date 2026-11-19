# =================== AIPass ====================
# Name: one_logger_content.py
# Description: One Logger Standards Content Handler
# Version: 1.2.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""
One Logger Standards Content Handler
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_one_logger_standards() -> str:
    """Return formatted one_logger standards content with Rich markup"""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Prax is the only logging system. A file that logs uses a prax door; a file that",
        "  logs nothing owes no import. Any other logger is rejected, handlers included.",
        "",
        "[bold cyan]THE FOUR KEYS (AST, every production file):[/bold cyan]",
        "  [red]K0[/red] an import of logging or a logging submodule",
        "  [red]K1[/red] a class defining two or more of debug, info, warning, error, critical",
        "  [red]K2[/red] a file opened for writing whose path resolves, in the module, to a .log name",
        "  [red]K3[/red] a write wrapper sending its message to stderr, or printing it time-stamped",
        "",
        "[bold cyan]NO WAIVERS:[/bold cyan] a bypass row waives nothing. K0 and K1 pass only what prax's",
        "  LOGGING_ALLOWED and LOGGER_DOORS name; logging_allowed names the bridges' crash record.",
        "  An unreadable prax list refuses every file.",
        "",
        "[bold cyan]SCORING:[/bold cyan] ADVISORY: scored per file, never in the branch average.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]from aipass.prax import logger[/green]   (a loop on the watched log path: prax's trail door)",
        "  [green]from aipass.prax import append_jsonl[/green] for a record; a transcript leaves the .log suffix",
    ]

    json_handler.log_operation("content_served", {"standard": "one_logger"})
    return "\n".join(lines)
