# =================== AIPass ====================
# Name: silent_catch_content.py
# Description: Silent Catch Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Silent Catch Standards Content Handler

Provides formatted Silent Catch standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_silent_catch_standards() -> str:
    """Return formatted silent_catch standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Never silently swallow exceptions. Every except block must either",
        "  [yellow]log the error[/yellow] or [yellow]re-raise[/yellow] it. Silent catches hide",
        "  failures and make debugging impossible.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Parses Python files with [dim]ast.parse()[/dim] and walks every",
        "  [dim]ExceptHandler[/dim] node. An except block is flagged when its body:",
        "",
        "  1. Contains [red]no[/red] [dim]logger.<level>()[/dim] call",
        "     (error, warning, warn, info, debug, exception, critical)",
        "  2. Contains [red]no[/red] [dim]raise[/dim] statement",
        "",
        "  [yellow]Also detects no-op bodies:[/yellow]",
        "  - [dim]pass[/dim]",
        "  - [dim]...[/dim] (Ellipsis)",
        "  - Bare string constants (docstring-style placeholders)",
        "",
        "  [yellow]Skips:[/yellow]",
        "  - [dim]__init__.py[/dim] files",
        "  - Non-.py files",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad -- silent catch (pass):[/red]",
        "  [dim]try:[/dim]",
        "  [dim]    result = do_something()[/dim]",
        "  [dim]except Exception:[/dim]",
        "  [dim]    pass[/dim]",
        "",
        "  [red]Bad -- silent catch (bare variable):[/red]",
        "  [dim]try:[/dim]",
        "  [dim]    data = load_file(path)[/dim]",
        "  [dim]except OSError as e:[/dim]",
        "  [dim]    error_msg = str(e)  # stored but never logged or raised[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  [green]Good -- log the error:[/green]",
        "  [dim]try:[/dim]",
        "  [dim]    result = do_something()[/dim]",
        "  [dim]except Exception as e:[/dim]",
        '  [dim]    logger.error(f"Operation failed: {{e}}")[/dim]',
        "",
        "  [green]Good -- re-raise:[/green]",
        "  [dim]try:[/dim]",
        "  [dim]    data = load_file(path)[/dim]",
        "  [dim]except OSError:[/dim]",
        "  [dim]    raise[/dim]",
        "",
        "  [green]Good -- log and handle:[/green]",
        "  [dim]try:[/dim]",
        "  [dim]    data = load_file(path)[/dim]",
        "  [dim]except OSError as e:[/dim]",
        '  [dim]    logger.warning(f"Could not load: {{e}}")[/dim]',
        "  [dim]    data = default_value[/dim]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Checks every .py file in the branch individually via AST parsing",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per file (silent catch blocks)",
        "  [green]100[/green] = no silent catches found",
        "  [red]0[/red] = one or more silent catches found",
        "  Reports up to 3 offending line numbers, plus count of extras",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard and file-level",
        "  bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (silent_catch)[/dim]",
        "  [dim]Checker: silent_catch_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "silent_catch"})
    return "\n".join(lines)
