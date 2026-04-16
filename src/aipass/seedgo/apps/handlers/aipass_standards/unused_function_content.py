# =================== AIPass ====================
# Name: unused_function_content.py
# Description: Unused Function Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Unused Function Standards Content Handler

Provides formatted Unused Function standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_unused_function_standards() -> str:
    """Return formatted unused_function standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Dead code is maintenance burden. Functions that are defined but",
        "  never called anywhere in the branch should be removed or wired up.",
        "  Every function should earn its place.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Branch-level analysis in four phases:",
        "",
        "  [yellow]Phase 1 -- Collect files:[/yellow]",
        "  Gathers all .py files in the branch, skipping irrelevant dirs",
        "  (tests, __pycache__, .archive, logs, tools, .trinity, etc.)",
        "",
        "  [yellow]Phase 2 -- Build corpus:[/yellow]",
        "  Reads all files and strips non-code content:",
        "  - Triple-quoted strings (docstrings, multiline literals)",
        "  - Comment lines",
        '  - [dim]if __name__ == "__main__":[/dim] blocks',
        "",
        "  [yellow]Phase 3 -- Extract functions:[/yellow]",
        "  AST-parses each file to find [dim]def[/dim] and [dim]async def[/dim]",
        "  definitions. Excludes:",
        "  - Dunder methods ([dim]__init__[/dim], [dim]__str__[/dim], [dim]__repr__[/dim], etc.)",
        "  - [dim]main()[/dim] and [dim]handle_command()[/dim] (framework conventions)",
        "  - Any function with a decorator ([dim]@property[/dim], [dim]@staticmethod[/dim], etc.)",
        "",
        "  [yellow]Phase 4 -- Reference counting:[/yellow]",
        "  For each function name, counts word-bounded occurrences in the",
        "  cleaned corpus. Subtracts definition lines. If [dim]call_refs <= 0[/dim],",
        "  the function is flagged as unused.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Unused:[/red] Function defined but never referenced elsewhere",
        "",
        "  [dim]def _calculate_delta(a, b):[/dim]",
        "  [dim]    return a - b[/dim]",
        "  [dim]# ^ never called anywhere in the branch[/dim]",
        "",
        "  [dim]def legacy_export(data):[/dim]",
        "  [dim]    ...  # leftover from old feature[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  [green]Option 1 -- Remove it:[/green]",
        "  If the function is truly dead code, delete it.",
        "",
        "  [green]Option 2 -- Wire it up:[/green]",
        "  If the function should be used, call or import it somewhere.",
        "",
        "  [green]Option 3 -- Add a decorator:[/green]",
        "  If the function is called externally (API, callback, test hook),",
        "  add a decorator to exclude it from detection:",
        "  [dim]@some_decorator[/dim]",
        "  [dim]def external_callback(event):[/dim]",
        "  [dim]    ...[/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Runs once per branch (not per file). Entry point: [dim]check_branch()[/dim]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Score = [dim]clean_functions / total_functions * 100[/dim]",
        "  Reports up to 15 unused functions with file:line locations",
        "  If no eligible functions found: score = [green]100[/green]",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]EXCLUDED FROM FLAGGING:[/bold cyan]",
        "  - Dunder methods ([dim]__init__[/dim], [dim]__str__[/dim], etc.)",
        "  - [dim]main()[/dim] and [dim]handle_command()[/dim]",
        "  - Decorated functions ([dim]@property[/dim], [dim]@staticmethod[/dim], etc.)",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file,",
        "  and file+line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (unused_function)[/dim]",
        "  [dim]Checker: unused_function_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "unused_function"})
    return "\n".join(lines)
