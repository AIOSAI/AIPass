# =================== AIPass ====================
# Name: shebang_content.py
# Description: Shebang Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-09
# Modified: 2026-03-09
# =============================================

"""
Shebang Standards Content Handler

Provides formatted shebang standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_shebang_standards() -> str:
    """Return formatted shebang standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold red]SHEBANG STANDARD[/bold red]",
        "",
        "[bold cyan]CORE RULE:[/bold cyan] No shebangs in pip-installable packages",
        "",
        "[yellow]RULE:[/yellow] AIPass is pip-installed -- all execution goes through",
        "  pyproject.toml entry points or python3 -m",
        "  Shebang lines (#!/...) are unnecessary and must be removed",
        "",
        "─" * 70,
        "",
        "[bold cyan]WHY SHEBANGS ARE WRONG:[/bold cyan]",
        "",
        "  [red]✗[/red] pip entry points handle execution -- shebangs are redundant",
        "  [red]✗[/red] python3 -m handles module execution -- no shebang needed",
        "  [red]✗[/red] No files are executed directly (./script.py)",
        "  [red]✗[/red] Shebangs mislead -- suggests standalone script, not package module",
        "  [red]✗[/red] They're noise -- a line that does nothing in every file",
        "",
        "─" * 70,
        "",
        "[bold cyan]WHAT IS CHECKED:[/bold cyan]",
        "",
        "  [yellow]Scope:[/yellow] all_files -- every .py file is audited",
        "  [yellow]Check:[/yellow] Does line 1 start with [dim]#![/dim]?",
        "  [yellow]Pass:[/yellow]  No shebang found → [green]score 100[/green]",
        "  [yellow]Fail:[/yellow]  Shebang on line 1 → [red]score 0[/red]",
        "",
        "─" * 70,
        "",
        "[bold cyan]EXAMPLES:[/bold cyan]",
        "",
        "[bold]Good (no shebang):[/bold]",
        "  [green]✓[/green] [dim]# =================== AIPass ====================[/dim]",
        "  [green]✓[/green] [dim]# Name: seedgo.py[/dim]",
        "  [green]✓[/green] [dim]# Description: Seedgo Entry Point[/dim]",
        "",
        "[bold]Bad (shebang on line 1):[/bold]",
        "  [red]✗[/red] [dim]#!/usr/bin/env python3[/dim]",
        "  [red]✗[/red] [dim]#!/usr/bin/python3[/dim]",
        "  [red]✗[/red] [dim]#!/usr/bin/python[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  Delete line 1 if it starts with [dim]#![/dim]",
        "",
        "  [bold]Before:[/bold]",
        "  [dim]#!/usr/bin/env python3[/dim]",
        "  [dim]# =================== AIPass ====================[/dim]",
        "",
        "  [bold]After:[/bold]",
        "  [dim]# =================== AIPass ====================[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [green]100[/green] - No shebang on line 1",
        "  [red]  0[/red] - Shebang found on line 1",
        "  [red]  0[/red] - File not found / not readable",
        "  [green]100[/green] - Bypassed via .seedgo/bypass.json",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (shebang)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "shebang"})
    return "\n".join(lines)
