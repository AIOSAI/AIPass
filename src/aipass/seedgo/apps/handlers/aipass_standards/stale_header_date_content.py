# =================== AIPass ====================
# Name: stale_header_date_content.py
# Description: Stale Header Date Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Stale Header Date Standards Content Handler

Provides formatted Stale Header Date standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_stale_header_date_standards() -> str:
    """Return formatted stale_header_date standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1 item 5):[/bold cyan]",
        "  The META header's [green]# Modified: <date>[/green] is a claim about the file. It goes",
        "  stale the moment a change lands without moving it. @backup: 14 of 14 headers",
        "  read [red]2026-09-22[/red] after b92e0361 rewrote every file on 2026-09-23.",
        "",
        "[bold cyan]THE DATE OF TRUTH:[/bold cyan]",
        "  The author date of the file's last commit. A file with an uncommitted change,",
        "  or one never committed, is judged as of TODAY -- so a change that did not move",
        "  the date is convicted at the edit, and one that moved it passes at once.",
        "",
        "[bold cyan]THE FIRST CHECKER TO READ GIT -- AND WHEN IT DECLINES:[/bold cyan]",
        "  Read-only: rev-parse, log, diff --name-only, ls-files, one batch per directory.",
        "  No git, no work tree, a [yellow]shallow clone[/yellow] (every file's last commit is HEAD), or",
        "  a file with no history: the file is NOT APPLICABLE and stays out of the",
        "  average. A 100 would claim a measurement that never happened. CI's seedgo-audit",
        "  job checks out with fetch-depth: 0, so the gate sees full history.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25, 594 fleet test files):[/bold cyan]",
        "  433 judged, [red]326 stale[/red], 107 current, 161 declined. 182 more than 30 days behind.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file: 0 stale, 100 current, out of the average when declined.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Move Modified: to the date of the change.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "stale_header_date"})
    return "\n".join(lines)
