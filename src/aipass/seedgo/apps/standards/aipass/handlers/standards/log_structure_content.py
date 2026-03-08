"""
Log Structure Standards Content Handler

Provides formatted display of log structure standards for terminal output.
"""

# =================== AIPass ====================
# Name: log_structure_content.py
# Description: Log Structure Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-06
# Modified: 2026-03-06
# =============================================


from typing import List


def get_log_structure_standards() -> List[str]:
    """Return formatted log structure standards for display."""
    lines = [
        "[bold red]MODULE LOG STRUCTURE[/bold red]",
        "",
        "[yellow]CORE PRINCIPLE:[/yellow] Every module produces local logs in its own logs/ directory",
        "",
        "[bold cyan]REQUIREMENTS:[/bold cyan]",
        "  [green]1.[/green] Module has a [bold]logs/[/bold] directory at its root",
        "  [green]2.[/green] Log files written to module-local path, not just system_logs/",
        "  [green]3.[/green] No hardcoded absolute log paths (no /home/username/...)",
        "",
        "[bold cyan]DIRECTORY PATTERN:[/bold cyan]",
        "  [dim]my_module/[/dim]",
        "  [dim]  apps/[/dim]",
        "  [dim]    modules/[/dim]",
        "  [dim]    handlers/[/dim]",
        "  [dim]  logs/           <-- module-local logs[/dim]",
        "  [dim]  tests/[/dim]",
        "",
        "[bold cyan]LOG PATH PATTERN:[/bold cyan]",
        "  [green]CORRECT:[/green]",
        "  [dim]  LOG_DIR = Path(__file__).resolve().parents[N] / 'logs'[/dim]",
        "  [dim]  log_path = LOG_DIR / 'module_name.log'[/dim]",
        "",
        "  [red]WRONG:[/red]",
        "  [dim]  log_path = '/absolute/path/system_logs/module.log'[/dim]",
        "  [dim]  log_path = Path.home() / 'logs' / 'module.log'[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Examples: seedgo/logs/, trigger/logs/[/dim]",
    ]
    return lines
