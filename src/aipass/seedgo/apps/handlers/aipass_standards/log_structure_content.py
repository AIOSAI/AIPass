# =================== AIPass ====================
# Name: log_structure_content.py
# Description: Log Structure Standards Content Handler
# Version: 1.2.0
# Created: 2026-03-06
# Modified: 2026-03-17
# =============================================

"""
Log Structure Standards Content Handler

Provides formatted display of log structure standards for terminal output.
Describes the two-tier logging model: system_logs/ at repo root,
logs/ at branch root only.
"""

from aipass.seedgo.apps.handlers.json import json_handler

def get_log_structure_standards() -> str:
    """Return formatted log structure standards for display."""
    lines = [
        "[bold red]TWO-TIER LOG STRUCTURE[/bold red]",
        "",
        "[yellow]CORE PRINCIPLE:[/yellow] Two tiers, two locations. System-wide logs aggregate",
        "  at repo root; per-branch logs live at the branch root only.",
        "",
        "[bold cyan]TWO-TIER MODEL:[/bold cyan]",
        "  [green]1.[/green] [bold]system_logs/[/bold] at repo root — system-wide aggregation ({branch}_{module}.log)",
        "  [green]2.[/green] [bold]logs/[/bold] at branch root — per-branch local logs",
        "",
        "[bold cyan]REQUIREMENTS:[/bold cyan]",
        "  [green]1.[/green] [bold]logs/[/bold] directory exists at the branch root",
        "  [green]2.[/green] No hardcoded absolute paths to .log files",
        "  [green]3.[/green] No /home/ references in logging configuration",
        "",
        "[bold cyan]DIRECTORY LAYOUT:[/bold cyan]",
        "  [dim]repo_root/[/dim]",
        "  [dim]  system_logs/                   <-- system-wide logs[/dim]",
        "  [dim]  src/aipass/{branch}/[/dim]",
        "  [dim]    logs/                        <-- branch-level logs (only here)[/dim]",
        "  [dim]    apps/[/dim]",
        "  [dim]      handlers/[/dim]",
        "  [dim]      modules/[/dim]",
        "",
        "[bold cyan]LOG PATH PATTERN:[/bold cyan]",
        "  [green]CORRECT:[/green]  Use prax's system_logger (auto-routes to correct tier)",
        "  [dim]  from aipass.prax.apps.modules.logger import system_logger[/dim]",
        "  [dim]  system_logger.info('message')  # prax handles tier routing[/dim]",
        "",
        "  [green]ALSO OK:[/green]  Relative path to branch-root logs/",
        "  [dim]  LOG_DIR = Path(__file__).resolve().parents[2] / 'logs'[/dim]",
        "  [dim]  log_path = LOG_DIR / 'my_handler.log'[/dim]",
        "",
        "  [red]WRONG:[/red]  logs/ at nested directories (old hierarchical pattern)",
        "  [dim]  LOG_DIR = Path(__file__).resolve().parent / 'logs'[/dim]",
        "  [dim]  # Creates logs/ inside handlers/ or modules/ — not two-tier[/dim]",
        "",
        "  [red]WRONG:[/red]  Hardcoded absolute paths",
        "  [dim]  path = '/absolute/path/to/system_logs/module.log'[/dim]",
        "  [dim]  path = Path.home() / 'logs' / 'module.log'[/dim]",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Prax logger: src/aipass/prax/apps/modules/logger.py[/dim]",
    ]
    json_handler.log_operation("standard_content_queried", {"standard": "log_structure"})
    return "\n".join(lines)
