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

import os
import sys
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error, warning
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.cli.help_flags import wants_help


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
    console.print("  [cyan]sweep[/cyan]     Delete log files older than 30 days")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print()
    console.print("  [dim]# Show log health summary + any oversized files[/dim]")
    console.print("  $ drone @prax log-audit audit")
    console.print()
    console.print("  [dim]# Truncate all oversized files to 1000 lines[/dim]")
    console.print("  $ drone @prax log-audit enforce")
    console.print()
    console.print("  [dim]# Delete log files older than 30 days[/dim]")
    console.print("  $ drone @prax log-audit sweep")
    console.print()


def _display_audit(files: list, summary: dict) -> None:
    """Display system_logs/ audit results."""
    console.print()
    console.print("[bold cyan]System Log Audit[/bold cyan] [dim](system_logs/)[/dim]")
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


def _display_branch_audit(files: list, summary: dict) -> None:
    """Display branch logs/ audit results."""
    console.print("[bold cyan]Branch Log Audit[/bold cyan] [dim](src/aipass/*/logs/)[/dim]")
    console.print(f"  Total files: {summary['total_files']}")
    console.print(f"  Total size: {summary['total_size_mb']} MB")
    if summary.get("largest_file"):
        console.print(f"  Largest: {summary['largest_file']} ({summary.get('largest_size_mb', 0)} MB)")

    if summary["healthy"]:
        console.print("[green]  Status: HEALTHY — no unbounded files[/green]")
    else:
        error(f"Status: {summary['oversized_count']} unbounded, {summary['critical_count']} critical")

    oversized = [f for f in files if f["status"] != "ok"]
    if oversized:
        console.print()
        console.print("[bold]Unbounded files (no rotation, exceeds size threshold):[/bold]")
        for f in oversized:
            status_color = "red" if f["status"] == "critical" else "yellow"
            rotation = "[green]rotated[/green]" if f["has_rotation"] else "[red]unrotated[/red]"
            console.print(
                f"  [{status_color}]{f['status'].upper()}[/{status_color}] "
                f"{f['branch']}/{f['name']}: {f['size_mb']} MB, "
                f"{f['lines']:,} lines, {rotation}"
            )
        console.print()
        console.print("[dim]Run 'drone @prax log-audit enforce' to truncate[/dim]")
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

    # A dashed help flag ANYWHERE wins — `enforce -h` asked about enforce, and
    # answering it by truncating every oversized log is the worst possible reply.
    # Placed after the ownership check above: prax.py tries each module in turn,
    # so a scan at the top of the function would hijack other modules' help.
    if wants_help(args):
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

        from aipass.prax.apps.handlers.logging.log_watchdog import (
            scan_branch_log_files,
            branch_log_health_summary,
        )

        branch_files = scan_branch_log_files()
        branch_summary = branch_log_health_summary()
        _display_branch_audit(branch_files, branch_summary)
        return True

    if subcmd == "enforce":
        _run_enforce()
        _run_branch_enforce()
        return True

    if subcmd == "sweep":
        _run_sweep()
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


def _run_branch_enforce():
    """Execute branch log enforcement and display results."""
    from aipass.prax.apps.handlers.logging.log_watchdog import enforce_branch_log_limits

    console.print("[bold cyan]Enforcing branch log limits...[/bold cyan]")
    actions = enforce_branch_log_limits()

    if not actions:
        console.print("[green]All branch logs within limits — nothing to truncate[/green]\n")
        return

    for action in actions:
        if action["truncated"]:
            console.print(
                f"  [red]TRUNCATED[/red] {action['branch']}/{action['name']}: "
                f"{action['size_mb']} MB, {action['original_lines']:,} → {action['new_lines']:,} lines"
            )
        else:
            console.print(f"  [green]OK[/green] {action['branch']}/{action['name']}: within limits")
    console.print()
    logger.info("[log-audit] Enforced branch log limits on %d files", len(actions))


def sweep_stale_logs():
    """Public re-export of the watchdog sweep for module-layer access."""
    from aipass.prax.apps.handlers.logging.log_watchdog import sweep_stale_logs as _sweep

    return _sweep()


def _run_sweep():
    """Execute stale log sweep and display results."""
    from aipass.prax.apps.handlers.logging.log_watchdog import sweep_stale_logs

    console.print("\n[bold cyan]Sweeping stale logs (>30 days)...[/bold cyan]")
    result = sweep_stale_logs()

    if not result["files_removed"]:
        console.print("[green]No stale logs found — nothing to delete[/green]\n")
        return

    for entry in result["removed"]:
        warning(f"DELETED {entry['name']}: {entry['age_days']} days old, {entry['size_kb']} KB")
    console.print(f"\n  Removed {result['files_removed']} file(s), reclaimed {result['total_reclaimed_kb']} KB\n")
    logger.info("[log-audit] Sweep removed %d stale files", result["files_removed"])


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if wants_help(sys.argv[1:]):
        print_help()
        sys.exit(0)

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    handle_command("log-audit", args)
