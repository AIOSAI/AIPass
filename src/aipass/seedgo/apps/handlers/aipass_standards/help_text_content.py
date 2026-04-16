# =================== AIPass ====================
# Name: help_text_content.py
# Description: Help Text Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Help Text Standards Content Handler

Provides formatted Help Text standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_help_text_standards() -> str:
    """Return formatted help_text standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  User-facing help text must tell users to run commands via",
        "  [yellow]drone @branch[/yellow], never via [red]python3 path/to/script.py[/red]",
        "  AIPass is a pip package -- all execution goes through drone entry points",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans string literals (single-line and multiline) for instructional",
        "  references to [red]python3[/red] or [red]python[/red] as a command invocation",
        "",
        "  [yellow]Detects:[/yellow]",
        "  - [red]python3 some/script.py[/red] inside string literals",
        "  - [red]python -m module[/red] inside string literals",
        "  - References inside triple-quoted docstrings and help text",
        "",
        "  [yellow]Ignores:[/yellow]",
        "  - Shebangs ([dim]#!/usr/bin/env python3[/dim])",
        "  - Comment lines ([dim]# python3 ...[/dim])",
        "  - Non-instructional references ([dim]python version[/dim])",
        "  - [dim]__init__.py[/dim] files (always skipped)",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  A violation occurs when a string literal tells the user to run",
        "  a python3/python command directly:",
        "",
        '  [red]Bad:[/red]  [dim]help_msg = "Run: python3 tools/scanner.py --check"[/dim]',
        '  [red]Bad:[/red]  [dim]print("Usage: python3 flow.py create plan_name")[/dim]',
        '  [red]Bad:[/red]  [dim]description = "Execute python -m aipass.seedgo"[/dim]',
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Replace python3/python command references with drone invocations:",
        "",
        '  [green]Good:[/green] [dim]help_msg = "Run: drone @seedgo scan --check"[/dim]',
        '  [green]Good:[/green] [dim]print("Usage: drone @flow create plan_name")[/dim]',
        '  [green]Good:[/green] [dim]description = "Execute drone @seedgo"[/dim]',
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Checks every .py file in the branch individually",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per file (help text references)",
        "  [green]100[/green] = no violations found",
        "  [red]0[/red] = one or more violations found",
        "  Reports first 3 offending line numbers, plus count of extras",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file,",
        "  and line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (help_text)[/dim]",
        "  [dim]Checker: help_text_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "help_text"})
    return "\n".join(lines)
