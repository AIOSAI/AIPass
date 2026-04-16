# =================== AIPass ====================
# Name: debug_print_content.py
# Description: Debug Print Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Debug Print Standards Content Handler

Provides formatted Debug Print standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_debug_print_standards() -> str:
    """Return formatted debug_print standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Bare [red]print()[/red] calls have no place in production code.",
        "  Use structured logging (Prax logger) or Rich console output instead.",
        "  print() is unstructured, unsearchable, and invisible to monitoring.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans every .py file for bare [dim]print([/dim] calls that are NOT:",
        "",
        "  [green]Excluded automatically:[/green]",
        "  - Inside docstrings (triple-quoted regions)",
        "  - On comment lines ([dim]# print(...)[/dim])",
        "  - In doctest / interactive examples ([dim]>>> print(...)[/dim])",
        '  - Inside [dim]if __name__ == "__main__":[/dim] blocks',
        "  - Method calls like [dim]console.print()[/dim] or [dim]logger.print()[/dim]",
        "  - __init__.py files",
        "  - Test files (test_*.py, *_test.py, conftest.py)",
        "",
        "  The regex [dim](?<![.#\\w])print\\([/dim] ensures only standalone",
        "  print() is caught -- not console.print(), not comments.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  Any bare print() call outside excluded zones is a violation.",
        "",
        "  [red]Bad:[/red]",
        '  [dim]print(f"Processing {name}")[/dim]',
        '  [dim]print("DEBUG: value =", result)[/dim]',
        "  [dim]print(data)[/dim]",
        "",
        "  [green]Good -- use structured logging:[/green]",
        '  [dim]logger.info(f"Processing {name}")[/dim]',
        '  [dim]logger.debug(f"value = {result}")[/dim]',
        "",
        "  [green]Good -- use Rich console output:[/green]",
        '  [dim]console.print(f"[cyan]Processing {name}[/cyan]")[/dim]',
        "",
        "  Violation message example:",
        "  [dim]3 bare print() call(s) on lines 42, 78, 115[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  1. Search for bare [dim]print([/dim] in your file",
        "  2. Replace with the appropriate alternative:",
        "     [green]For logging:[/green] logger.info(), logger.debug(), etc.",
        "     [green]For user output:[/green] console.print() with Rich markup",
        "  3. If the print() is in a [dim]__main__[/dim] block, it is allowed",
        "  4. Re-run the audit to confirm zero violations",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Runs against every .py file in the branch. Skips __init__.py and",
        "  test files (test_*.py, *_test.py, conftest.py).",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (0 violations) or [red]fail[/red] (any violations)",
        "  Score: 100 if passed, 0 if failed",
        "  Threshold: score >= 75 to pass overall",
        "  Line-level bypass filtering is supported -- bypassed lines are",
        "  excluded before counting violations.",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "debug_print", "file": "path/to/file.py"}[/dim]',
        "  Or bypass specific lines:",
        '  [dim]{"standard": "debug_print", "file": "file.py", "lines": [42, 78]}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (debug_print)[/dim]",
        "  [dim]Checker: debug_print_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "debug_print"})
    return "\n".join(lines)
