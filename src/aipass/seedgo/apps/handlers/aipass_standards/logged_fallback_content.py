# =================== AIPass ====================
# Name: logged_fallback_content.py
# Description: Logged Fallback Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Logged Fallback Standards Content Handler

Provides formatted Logged Fallback standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_logged_fallback_standards() -> str:
    """Return formatted logged_fallback standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  silent_catch acquits an except that logs. This rule reads what it RETURNS: a handler",
        "  that returns a value the success path can also return hands its caller a failure",
        "  dressed as an answer. Logging never acquits.",
        "",
        "[bold cyan]THE SHAPE:[/bold cyan]",
        "  An except that does not raise and ENDS in [red]return <literal default>[/red]",
        "  (a constant, an empty container, or a string built from the exception), in a",
        "  function where some return OUTSIDE every handler returns the same literal, or a",
        "  name first bound to it ([red]results = [][/red] ... [red]return results[/red]).",
        "",
        "[bold cyan]NOT CONVICTED:[/bold cyan]",
        "  [yellow]a sentinel[/yellow] no success return produces  [yellow]a handler that raises[/yellow]",
        "  [yellow]assign-and-fall-through[/yellow] (not read)  [yellow]generators[/yellow]",
        "  [yellow]finally returns[/yellow]",
        "  [yellow]a success return of a call or parameter[/yellow]  nested defs judged on their own.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25):[/bold cyan]",
        "  1,216 product files. [red]496 hits in 230 files[/red], 16 branches. On the 40-hit sample:",
        "  8 of 12 true hits kept, 8 of 13 sentinels dropped, 3 of 12 by-design dropped.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Re-raise, or return a value the success path cannot return and name it in the docstring.[/green]",
        "  A log line beside the default is not a cure: the caller still reads an answer.",
    ]

    json_handler.log_operation("content_served", {"standard": "logged_fallback"})
    return "\n".join(lines)
