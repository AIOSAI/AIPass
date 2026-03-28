# =================== AIPass ====================
# Name: error_handling_content.py
# Description: Error Handling Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-27
# Modified: 2026-03-27
# =============================================

"""
Error Handling Standards Content Handler

Provides formatted error handling standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_error_handling_standards() -> str:
    """Return formatted error_handling standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Errors must tell the truth. Silent failures hide bugs and erode",
        "  trust in the codebase. Every except block must handle the error",
        "  meaningfully — log it, return it, or re-raise it.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  File-level analysis of try/except patterns:",
        "",
        "  [yellow]Detection:[/yellow]",
        "  Scans all Python files for [dim]try/except[/dim] blocks",
        "  Flags silent failures: [dim]except: pass[/dim] or [dim]except Exception: pass[/dim]",
        "  Skips files with no try/except (not applicable)",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Fail:[/red] Silent failure detected — [dim]except: pass[/dim] with no",
        "  logging, return, or re-raise",
        "",
        "  [green]Pass:[/green] All except blocks have meaningful handling",
        "  (logging, return values, re-raise, or other statements)",
        "",
        "[bold cyan]CODE EXAMPLES:[/bold cyan]",
        "",
        "  [green]Good:[/green]",
        "  [dim]try:[/dim]",
        "    [dim]result = api_call()[/dim]",
        "  [dim]except Exception as e:[/dim]",
        "    [dim]logger.error(f'API call failed: {e}')[/dim]",
        "    [dim]return {'success': False, 'error': str(e)}[/dim]",
        "",
        "  [red]Bad:[/red]",
        "  [dim]try:[/dim]",
        "    [dim]result = api_call()[/dim]",
        "  [dim]except:[/dim]",
        "    [dim]pass  # Silent failure — error swallowed[/dim]",
        "",
        "[bold cyan]PHILOSOPHY:[/bold cyan]",
        "",
        "  [yellow]Fix error handling BEFORE fixing bugs.[/yellow]",
        "  If errors lie, you can't debug effectively.",
        "  Honest errors → faster debugging → reliable code.",
        "",
        "  The debug cycle:",
        "  [dim]1. Fix error handling — make errors tell the truth[/dim]",
        "  [dim]2. Then fix the actual bug[/dim]",
        "  [dim]3. See clean pass with honest outputs[/dim]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "",
        "  Score = (passed_checks / total_checks) * 100",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "  No try/except blocks: [green]100%[/green] (not applicable)",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Runs on every Python file. Entry point: [dim]check_module()[/dim]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] — supports standard-level,",
        "  file-level, and line-level bypass rules",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: error_handling_check.py[/dim]",
        "  [dim]Standard label: ERROR_HANDLING[/dim]",
        "  [dim]Previously: testing_check.py (renamed for clarity)[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "error_handling"})
    return "\n".join(lines)
