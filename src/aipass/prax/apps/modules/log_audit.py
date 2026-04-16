# =================== AIPass ====================
# Name: log_audit.py
# Description: PRAX Log Audit Command
# Version: 0.1.0
# Created: 2026-02-26
# Modified: 2026-03-09
# =============================================

"""
PRAX Log Audit Module

Implements the 'log-audit' command for system log health monitoring.
Scans the system_logs/ directory for oversized files, reports status,
and optionally enforces size limits by truncating bloated logs.
"""

import sys
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.prax.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection - shows connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Log Audit Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Monitor and enforce system log size limits")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]prax/handlers/logging/[/cyan]")
    console.print("    [dim]- log_watchdog.py (scan_log_files, enforce_log_limits, log_health_summary)[/dim]")
    console.print()

    console.print("[dim]Run 'drone @prax log-audit --help' for usage[/dim]")
    console.print()


def print_help():
    """Drone-compliant help output"""
    console.print()
    console.print("[bold cyan]PRAX Log Audit[/bold cyan]")
    console.print()

    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Scan system_logs/ for oversized files and enforce rotation limits")
    console.print()

    console.print("[yellow]Subcommands:[/yellow]")
    console.print()
    console.print("  [cyan]audit[/cyan]     Show log health summary + any oversized files")
    console.print("  [cyan]enforce[/cyan]   Truncate all oversized files to 1000 lines")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print()
    console.print("  [dim]# Show log health summary + any oversized files[/dim]")
    console.print("  $ drone @prax log-audit audit")
    console.print()
    console.print("  [dim]# Truncate all oversized files to 1000 lines[/dim]")
    console.print("  $ drone @prax log-audit enforce")
    console.print()


def _display_audit(files: list, summary: dict) -> None:
    """Display audit results."""
    console.print()
    console.print("[bold cyan]System Log Audit[/bold cyan]")
    console.print(f"  Total files: {summary['total_files']}")
    console.print(f"  Total lines: {summary['total_lines']:,}")
    if summary.get("largest_file"):
        console.print(f"  Largest: {summary['largest_file']} ({summary.get('largest_lines', 0):,} lines)")
    else:
        console.print("  Largest: (no log files found)")

    if summary["healthy"]:
        console.print("[green]  Status: HEALTHY — all logs within limits[/green]")
    else:
        error(f"Status: {summary['oversized_count']} oversized, {summary['critical_count']} critical")

    # Show oversized files
    oversized = [f for f in files if f["status"] != "ok"]
    if oversized:
        console.print()
        console.print("[yellow]Oversized files:[/yellow]")
        for f in oversized:
            status_color = "red" if f["status"] == "critical" else "yellow"
            console.print(
                f"  [{status_color}]{f['status'].upper()}[/{status_color}] "
                f"{f['name']}: {f['lines']:,} lines ({f['size_kb']} KB)"
            )
        console.print()
        console.print("[dim]Run 'drone @prax log-audit enforce' to truncate oversized files[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle log-audit command

    Args:
        command: Command name
        args: Command arguments ('enforce' to truncate)

    Returns:
        True if command was handled
    """
    if command != "log-audit":
        return False

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    from aipass.prax.apps.handlers.logging.log_watchdog import (
        scan_log_files,
        log_health_summary,
    )

    subcmd = args[0]
    json_handler.log_operation("log_audit_executed", {"mode": subcmd})

    if subcmd == "audit":
        files = scan_log_files()
        summary = log_health_summary()
        _display_audit(files, summary)
        return True

    if subcmd == "enforce":
        _run_enforce()
        return True

    error(f"Unknown log-audit subcommand: {subcmd}")
    print_help()
    return True


def _run_enforce():
    """Execute log enforcement and display results."""
    from aipass.prax.apps.handlers.logging.log_watchdog import enforce_log_limits

    console.print("\n[bold cyan]Enforcing log limits...[/bold cyan]")
    actions = enforce_log_limits()

    if not actions:
        console.print("[green]All logs within limits — nothing to truncate[/green]\n")
        return

    for action in actions:
        if action["truncated"]:
            console.print(
                f"  [yellow]TRUNCATED[/yellow] {action['name']}: "
                f"{action['original_lines']:,} → {action['new_lines']:,} lines"
            )
        else:
            console.print(f"  [green]OK[/green] {action['name']}: within limits")
    console.print()
    logger.info("[log-audit] Enforced limits on %d files", len(actions))


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if "--help" in sys.argv:
        print_help()
        sys.exit(0)

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    handle_command("log-audit", args)
