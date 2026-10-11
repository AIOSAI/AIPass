# =================== AIPass ====================
# Name: todo_content.py
# Description: TODO Standards Content Handler
# Version: 1.0.1
# Created: 2026-03-22
# Modified: 2026-10-03
# =============================================

"""
TODO Standards Content Handler

Provides formatted TODO standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_todo_standards() -> str:
    """Return formatted todo standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Code should be complete. TODO, FIXME, HACK, and XXX comments",
        "  indicate unfinished work, known hacks, or code needing attention.",
        "  Clean code has none of these -- resolve them before shipping.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans Python source files for comment tags (case-insensitive):",
        "",
        "  [yellow]Detected tags:[/yellow]",
        "  - [red]TODO[/red]  -- planned but unfinished work",
        "  - [red]FIXME[/red] -- known bug or broken behavior",
        "  - [red]HACK[/red]  -- workaround that should be replaced",
        "  - [red]XXX[/red]   -- dangerous or problematic code",
        "",
        "  [yellow]Pattern:[/yellow] [dim]# TODO: text[/dim], [dim]# FIXME(user): text[/dim],",
        "  [dim]# HACK ...[/dim], inline [dim]x = 1  # XXX temporary[/dim]",
        "",
        "  [yellow]Skips:[/yellow]",
        "  - [dim]__init__.py[/dim] files",
        "  - Any string or docstring: only a real comment counts, read from the tokenizer",
        "  - A file Python cannot tokenize fails by name ([dim]File tokenizable[/dim])",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad:[/red]  [dim]# TODO: implement retry logic[/dim]",
        "  [red]Bad:[/red]  [dim]# FIXME: this breaks on empty input[/dim]",
        "  [red]Bad:[/red]  [dim]result = hack_around_bug()  # HACK: remove later[/dim]",
        "  [red]Bad:[/red]  [dim]# XXX: dangerous -- needs review[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Actually do the work the comment describes, then remove it:",
        "",
        "  [red]Before:[/red]",
        "  [dim]# TODO: add input validation[/dim]",
        "  [dim]def process(data):[/dim]",
        "  [dim]    return transform(data)[/dim]",
        "",
        "  [green]After:[/green]",
        "  [dim]def process(data):[/dim]",
        "  [dim]    if not data:[/dim]",
        '  [dim]        raise ValueError("data cannot be empty")[/dim]',
        "  [dim]    return transform(data)[/dim]",
        "",
        "  If the work cannot be done now, create a flow plan or ticket",
        "  instead of leaving a comment in the code.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Checks every .py file in the branch individually",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per file (TODO/FIXME comments)",
        "  [green]100[/green] = no TODO-type comments found",
        "  [red]0[/red] = one or more found (reports tag breakdown: TODO: 2, FIXME: 1)",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file,",
        "  and line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (todo)[/dim]",
        "  [dim]Checker: todo_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "todo"})
    return "\n".join(lines)
