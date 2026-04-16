# =================== AIPass ====================
# Name: deep_nesting_content.py
# Description: Deep Nesting Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Deep Nesting Standards Content Handler

Provides formatted Deep Nesting standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_deep_nesting_standards() -> str:
    """Return formatted deep_nesting standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Deeply nested control flow is hard to read, hard to test, and",
        "  error-prone. Functions should be flat -- extract helpers instead",
        "  of nesting deeper.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Parses Python source with the AST module and walks every function",
        "  (sync and async). Counts nesting depth for each control-flow node:",
        "",
        "  [yellow]Nesting nodes:[/yellow] If, For, While, Try, With, ExceptHandler",
        "",
        "  [bold red]Threshold: depth > 4 is a violation[/bold red]",
        "",
        "  The checker measures the maximum nesting depth inside each function",
        "  body. Depth 4 is acceptable — depth 5+ is a violation.",
        "",
        "  [yellow]Skipped:[/yellow] __init__.py files are excluded.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  Any function whose max nesting depth exceeds 4 is a violation.",
        "",
        "  [red]Bad (depth 5):[/red]",
        "  [dim]def process(items):[/dim]",
        "  [dim]    for item in items:              # depth 1[/dim]",
        "  [dim]        if item.valid:               # depth 2[/dim]",
        "  [dim]            try:                     # depth 3[/dim]",
        "  [dim]                for sub in item:     # depth 4[/dim]",
        "  [dim]                    if sub.ok:       # depth 5 -- VIOLATION[/dim]",
        "  [dim]                        handle(sub)[/dim]",
        "",
        "  [green]Good (depth 4 or less):[/green]",
        "  [dim]def process(items):[/dim]",
        "  [dim]    for item in items:              # depth 1[/dim]",
        "  [dim]        if item.valid:               # depth 2[/dim]",
        "  [dim]            try:                     # depth 3[/dim]",
        "  [dim]                _handle_subitems(item)  # depth 4, extracted[/dim]",
        "",
        "  [green]Good -- use early returns to flatten:[/green]",
        "  [dim]def process_item(item):[/dim]",
        "  [dim]    if not item.valid:[/dim]",
        "  [dim]        return[/dim]",
        "  [dim]    try:[/dim]",
        "  [dim]        handle(item)[/dim]",
        "",
        "  Violation message example:",
        "  [dim]2 functions exceed nesting limit: process() depth 5 line 15, build() depth 6 line 88[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  1. Identify the deeply nested function from the violation message",
        "  2. Refactor using one or more of these strategies:",
        "     [green]Extract helper:[/green] Move inner logic to a separate function",
        "     [green]Early return:[/green] Invert conditions and return early",
        "     [green]Guard clauses:[/green] Handle edge cases at the top",
        "     [green]Flatten loops:[/green] Use comprehensions or itertools",
        "  3. Re-run the audit to confirm depth <= 4",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Runs against every .py file in the branch. Skips __init__.py.",
        "  Uses AST parsing so syntax errors result in the file being skipped",
        "  (no crash, no false positives).",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (all functions within limit)"
        " or [red]fail[/red] (any function exceeds depth 4)",
        "  Score: 100 if passed, 0 if failed",
        "  Threshold: score >= 75 to pass overall",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "deep_nesting", "file": "path/to/file.py"}[/dim]',
        "  Or bypass specific lines:",
        '  [dim]{"standard": "deep_nesting", "file": "file.py", "lines": [15]}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (deep_nesting)[/dim]",
        "  [dim]Checker: deep_nesting_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "deep_nesting"})
    return "\n".join(lines)
