# =================== AIPass ====================
# Name: log_audit.py
# Description: PRAX Log Audit Command
# Version: 0.3.0
# Created: 2026-02-26
# Modified: 2026-11-15
# =============================================

"""PRAX Log Audit Module: reports oversized logs and sweeps stale ones; never truncates (writers rotate themselves)."""

import sys
from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, error, warning
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.cli.help_flags import wants_help
from aipass.prax.apps.handlers.cli.arg_gate import UnknownArgument, refuse


def print_introspection():
    """Display module introspection - shows connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Log Audit Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Report oversized logs and sweep stale ones")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]prax/handlers/logging/[/cyan]")
    console.print("    [dim]- log_watchdog.py (scan_log_files, log_health_summary, sweep_stale_logs)[/dim]")
    console.print()

    console.print("[dim]Run 'drone @prax log-audit --help' for usage[/dim]")
    console.print()


def print_help():
    """Drone-compliant help output"""
    console.print()
    console.print("[bold cyan]PRAX Log Audit[/bold cyan]")
    console.print()

    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Report oversized logs in system_logs/ and branch logs/; writers rotate themselves")
    console.print()

    console.print("[yellow]Subcommands:[/yellow]")
    console.print()
    console.print("  [cyan]audit[/cyan]     Show log health summary + any oversized files")
    console.print("  [cyan]sweep[/cyan]     Delete .log files older than 30 days")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print()
    console.print("  [dim]# Show log health summary + any oversized files[/dim]")
    console.print("  $ drone @prax log-audit audit")
    console.print()
    console.print("  [dim]# Delete .log files older than 30 days[/dim]")
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


def handle_command(command: str, args: List[str]) -> bool:
    """Handle `log-audit audit|sweep`; True if handled, UnknownArgument for any other subcommand."""
    if command != "log-audit":
        return False

    if not args:
        print_introspection()
        return True

    # A dashed help flag ANYWHERE wins (`sweep -h` must not delete); after the ownership
    # check, since prax.py tries each module in turn.
    if wants_help(args):
        print_help()
        return True

    from aipass.prax.apps.handlers.logging.log_watchdog import (
        scan_log_files,
        log_health_summary,
    )

    subcmd = args[0]
    usage = "drone @prax log-audit --help"
    # A stray flag like `sweep --dry-run` must not run the real thing.
    if subcmd in ("audit", "sweep") and len(args) > 1:
        refuse("log-audit", args[1], usage)
    json_handler.log_operation("log_audit_executed", {"mode": subcmd})

    if subcmd == "audit":
        files = scan_log_files()
        summary = log_health_summary(files)
        _display_audit(files, summary)

        from aipass.prax.apps.handlers.logging.log_watchdog import (
            scan_branch_log_files,
            branch_log_health_summary,
        )

        branch_files = scan_branch_log_files()
        branch_summary = branch_log_health_summary(branch_files)
        _display_branch_audit(branch_files, branch_summary)
        return True

    if subcmd == "sweep":
        _run_sweep()
        return True

    # Refused, not "handled": a typo that exits 0 runs `&& next-step`; the raise carries the exit code.
    refuse("log-audit", subcmd, usage)


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

    try:
        handle_command("log-audit", sys.argv[1:])
    except UnknownArgument as exc:
        error(str(exc), suggestion=exc.usage)
        sys.exit(1)
