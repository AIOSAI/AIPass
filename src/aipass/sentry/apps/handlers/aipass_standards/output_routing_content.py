# =================== AIPass ====================
# Name: output_routing_content.py
# Description: Output Routing Standards Content Handler
# Version: 1.0.0
# Created: 2026-07-09
# Modified: 2026-11-02
# =============================================

"""
Output Routing Standards Content Handler

Provides formatted Output Routing standards content.
Module orchestrates, handler implements.
"""

import sys

from aipass.sentry.apps.handlers.json import json_handler

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def get_output_routing_standards() -> str:
    """Return formatted output_routing standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  User-facing error, success, and warning output MUST route through",
        "  @cli's semantic helpers — [dim]error()[/dim], [dim]success()[/dim],",
        "  [dim]warning()[/dim] — not raw console.print() with",
        "  status markup or emojis.",
        "",
        "[bold cyan]WHY IT MATTERS:[/bold cyan]",
        "  1. [yellow]Consistent formatting[/yellow] across all agents",
        "  2. [yellow]Exit-code correctness[/yellow] — error() carries the #661",
        "     failure-flag fix; raw markup bypasses it (errors exit 0)",
        "  3. [yellow]Stderr routing[/yellow] — error()/warning() write to stderr;",
        "     raw console.print() writes to stdout",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans every .py file for [dim]console.print()[/dim] or",
        "  [dim]err_console.print()[/dim] calls containing status indicators:",
        "",
        "  [white]Flagged patterns:[/white]",
        "  - Raw print with [dim][red]...[/red][/dim] markup → use error()",
        "  - Raw print with [dim][bold red]...[/bold red][/dim] markup → use error()",
        "  - Raw print with [dim][green]...[/green][/dim] + check emojis → use success()",
        "  - Raw print with status emojis → use helpers",
        "",
        "  [green]NOT flagged (legitimate Rich usage):[/green]",
        "  - [dim]console.print(table)[/dim] — Rich Table objects",
        "  - [dim]console.print(Panel(...))[/dim] — decorative panels",
        '  - [dim]console.print(f"[cyan]Info...[/cyan]")[/dim] — non-status color',
        '  - [dim]console.print(f"[dim]...[/dim]")[/dim] — decorative formatting',
        "  - Lines inside docstrings, comments, test files",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad — raw status output:[/red]",
        "  [dim]raw print with [red]Error: ...[/red] markup[/dim]",
        '  [dim]console.print("[green]...[/green] Done")[/dim]',
        '  [dim]console.print("... Failed")[/dim]',
        "",
        "  [green]Good — use @cli helpers:[/green]",
        "  [dim]from aipass.cli.apps.modules import error, success, warning[/dim]",
        '  [dim]error(f"Error: {msg}")[/dim]',
        '  [dim]success("Done")[/dim]',
        '  [dim]warning("Check configuration")[/dim]',
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  1. Import the helpers: [dim]from aipass.cli.apps.modules import error, success, warning[/dim]",
        "  2. Replace raw print with [dim][red]...[/red][/dim] markup → [dim]error(msg)[/dim]",
        "  3. Replace status-emoji prints with [dim]success(msg)[/dim] or [dim]warning(msg)[/dim]",
        "  4. Keep [dim]console.print()[/dim] for tables, panels, and non-status output",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Runs against every .py file in the branch.",
        "  Skips __init__.py and test files (test_*.py, *_test.py, conftest.py).",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (0 violations) or [red]fail[/red]",
        "  Score: 100 if passed, 0 if failed",
        "  Threshold: score >= 75 to pass overall",
        "  Line-level bypass filtering is supported.",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].sentry/bypass.json[/dim]:",
        '  [dim]{"standard": "output_routing", "file": "path/to/file.py"}[/dim]',
        "  Or bypass specific lines:",
        '  [dim]{"standard": "output_routing", "file": "file.py", "lines": [42]}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: sentry standards pack (output_routing)[/dim]",
        "  [dim]Checker: output_routing_check.py[/dim]",
        "  [dim]Related: GitHub #661 (error paths exit 0)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "output_routing"})
    return "\n".join(lines)
