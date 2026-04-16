# =================== AIPass ====================
# Name: commented_logger_content.py
# Description: Commented Logger Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Commented Logger Standards Content Handler

Provides formatted Commented Logger standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_commented_logger_standards() -> str:
    """Return formatted commented_logger standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Commented-out logger calls are dead logging -- noise that",
        "  obscures real code. Either [green]restore[/green] them or [green]remove[/green] them entirely.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans every .py file (except __init__.py) for lines matching:",
        "",
        "  [red]# logger.error(...)[/red]",
        "  [red]# logger.warning(...)[/red]",
        "  [red]# logger.info(...)[/red]",
        "  [red]# logger.debug(...)[/red]",
        "  [red]# logger.critical(...)[/red]",
        "  [red]# logger.exception(...)[/red]",
        "",
        "  The regex detects [dim]# logger.<level>([/dim] where level is one of:",
        "  error, warning, warn, info, exception, critical, debug.",
        "",
        "  [yellow]Docstrings are skipped[/yellow] -- triple-quoted regions are tracked and",
        "  excluded so documented examples do not trigger false positives.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  Any commented-out logger call outside a docstring is a violation.",
        "",
        "  [red]Bad:[/red]",
        '  [dim]# logger.info("Processing started")[/dim]',
        '  [dim]# logger.error(f"Failed: {err}")[/dim]',
        '  [dim]# logger.debug("Step completed")[/dim]',
        "",
        "  [green]Good -- either restore:[/green]",
        '  [dim]logger.info("Processing started")[/dim]',
        '  [dim]logger.error(f"Failed: {err}")[/dim]',
        "",
        "  [green]Good -- or remove entirely:[/green]",
        "  [dim](line deleted)[/dim]",
        "",
        "  The violation message reports the count and first three line numbers:",
        "  [dim]3 commented-out logger call(s) on lines 42, 78, 115[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  1. Search for [dim]# logger.[/dim] in your file",
        "  2. For each hit, decide:",
        "     [green]Restore:[/green] Uncomment if the logging is still needed",
        "     [green]Remove:[/green] Delete the line if it was leftover debug noise",
        "  3. Re-run the audit to confirm zero violations",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  The checker runs against every .py file in the branch (not just the",
        "  entry point). Files that are not .py or are __init__.py are skipped.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (0 violations) or [red]fail[/red] (any violations)",
        "  Score: 100 if passed, 0 if failed",
        "  Threshold: score >= 75 to pass overall",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "commented_logger", "file": "path/to/file.py"}[/dim]',
        "  Bypassed files return score 100 automatically.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (commented_logger)[/dim]",
        "  [dim]Checker: commented_logger_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "commented_logger"})
    return "\n".join(lines)
