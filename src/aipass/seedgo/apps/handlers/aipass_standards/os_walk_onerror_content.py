# =================== AIPass ====================
# Name: os_walk_onerror_content.py
# Description: Os Walk Onerror Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Os Walk Onerror Standards Content Handler

Provides formatted Os Walk Onerror standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_os_walk_onerror_standards() -> str:
    """Return formatted os_walk_onerror standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  os.walk swallows every OSError its scandir raises unless it is handed onerror=.",
        "  An unreadable subtree is skipped in silence and the run reports success over a",
        "  tree it never saw.",
        "",
        "[bold cyan]THE SHAPE:[/bold cyan]",
        "  A call to [red]os.walk[/red] with no [green]onerror=[/green] keyword, or onerror=None.",
        "  Aliases are followed: import os as o, from os import walk. Product code only.",
        "",
        "[bold cyan]NOT CONVICTED:[/bold cyan]",
        "  [yellow]onerror=[/yellow] any value but None  a third positional argument (the onerror slot)",
        "  [yellow]**kwargs[/yellow]  Path.rglob / Path.glob (no hook exists)  test files.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25):[/bold cyan]",
        "  1,214 product files, 13 os.walk calls. [red]8 convicted in 8 files[/red] across 6 branches;",
        "  5 already pass onerror.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]onerror= a callable that raises, or that records the error into what the function returns.[/green]",
        "  A callable that only logs is the same swallow with a line in a log: not a cure.",
    ]

    json_handler.log_operation("content_served", {"standard": "os_walk_onerror"})
    return "\n".join(lines)
