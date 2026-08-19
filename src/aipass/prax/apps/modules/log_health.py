# =================== AIPass ====================
# Name: log_health.py
# Description: PRAX Log Health Command — rate overview
# Version: 1.0.0
# Created: 2026-07-14
# Modified: 2026-07-14
# =============================================

"""
PRAX Log Health Module

Implements the 'log-health' command showing current log file growth rates
across system_logs/. Powered by the rate_tracker handler.
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
from aipass.cli.apps.modules import console, error
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.cli.help_flags import wants_help


def print_introspection():
    """Display module introspection."""
    console.print()
    console.print("[bold cyan]PRAX Log Health Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Show log file growth rates and detect runaway logs")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]prax/handlers/monitoring/[/cyan]")
    console.print("    [dim]- rate_tracker.py (scan_rates, get_snapshot)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @prax log-health --help' for usage[/dim]")
    console.print()


def print_help():
    """Drone-compliant help output."""
    console.print()
    console.print("[bold cyan]PRAX Log Health[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Monitor log file growth rates across system_logs/")
    console.print()
    console.print("[yellow]Subcommands:[/yellow]")
    console.print()
    console.print("  [cyan]scan[/cyan]      Scan all log files and show current rates")
    console.print("  [cyan]snapshot[/cyan]   Show last known rates (no new scan)")
    console.print()
    console.print("[yellow]Usage:[/yellow]")
    console.print()
    console.print("  [dim]# Scan and show current rates[/dim]")
    console.print("  $ drone @prax log-health scan")
    console.print()
    console.print("  [dim]# Show last known rates without scanning[/dim]")
    console.print("  $ drone @prax log-health snapshot")
    console.print()


def _display_rates(results: list, is_scan: bool) -> None:
    """Display rate results in a formatted table."""
    label = "Scan" if is_scan else "Snapshot"
    console.print()
    console.print(f"[bold cyan]Log Health {label}[/bold cyan] [dim](system_logs/)[/dim]")

    if not results:
        console.print("  [dim]No log files tracked yet[/dim]")
        console.print()
        return

    active = [r for r in results if r["rate_lines_per_min"] > 0]
    idle = [r for r in results if r["rate_lines_per_min"] == 0]
    flagged = [r for r in results if r.get("severity")]

    console.print(f"  Files tracked: {len(results)}")
    console.print(f"  Active: {len(active)}, Idle: {len(idle)}")
    if flagged:
        console.print(f"  [yellow]Flagged: {len(flagged)}[/yellow]")

    # A snapshot reports what an earlier scan measured. With no current
    # samples every file reads 0 lines/min, which is pixel-identical to a
    # genuinely quiet fleet — the zero has to name its own cause, or silence
    # means two different things.
    if not is_scan:
        ages = [r["age_seconds"] for r in results if r.get("age_seconds") is not None]
        if ages:
            console.print(f"  [dim]Newest sample: {min(ages):.0f}s ago[/dim]")
        else:
            console.print(
                "  [yellow]No recent measurements[/yellow] [dim]— the rates below are absent, "
                "not zero. Run 'drone @prax log-health scan' for current numbers, or check that "
                "Mission Control is running.[/dim]"
            )

    if flagged:
        console.print()
        console.print("[yellow]Flagged files:[/yellow]")
        for r in sorted(flagged, key=lambda x: x["rate_lines_per_min"], reverse=True):
            sev = r["severity"] or ""
            color = "red" if "critical" in sev else "yellow"
            console.print(
                f"  [{color}]{sev.upper()}[/{color}] "
                f"{r['file']}: {r['rate_lines_per_min']} lines/min "
                f"({r['size_kb']} KB) \\[{r['branch']}]"
            )

    if active:
        console.print()
        console.print("[cyan]Active files:[/cyan]")
        for r in sorted(active, key=lambda x: x["rate_lines_per_min"], reverse=True):
            if r.get("severity"):
                continue
            console.print(f"  {r['file']}: {r['rate_lines_per_min']} lines/min ({r['size_kb']} KB) \\[{r['branch']}]")

    if idle and len(idle) <= 10:
        console.print()
        console.print("[dim]Idle files:[/dim]")
        for r in sorted(idle, key=lambda x: x["file"]):
            console.print(f"  [dim]{r['file']}: {r['size_kb']} KB \\[{r['branch']}][/dim]")
    elif idle:
        console.print()
        console.print(f"  [dim]{len(idle)} idle files (0 lines/min)[/dim]")

    console.print()


def _get_event_callback():
    """Return trigger.fire if available, else None."""
    try:
        from aipass.trigger.apps.modules.core import trigger

        return trigger.fire
    except ImportError as exc:
        logger.info("[log-health] trigger not available: %s", exc)
        return None


def handle_command(command: str, args: List[str]) -> bool:
    """Handle log-health command.

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled
    """
    if command != "log-health":
        return False

    if not args:
        print_introspection()
        return True

    # A dashed help flag ANYWHERE wins — asking about `scan` must not sweep
    # system_logs/ or write an operation line. After the ownership check above,
    # so this module cannot answer another's help (prax.py routes by trial).
    if wants_help(args):
        print_help()
        return True

    from aipass.prax.apps.handlers.monitoring.rate_tracker import scan_rates, get_snapshot, configure
    from aipass.prax.apps.handlers.config.load import get_system_logs_dir

    configure(logs_dir=get_system_logs_dir(), event_callback=_get_event_callback())

    subcmd = args[0]
    logger.info("[log-health] %s", subcmd)
    json_handler.log_operation("log_health_executed", {"mode": subcmd})

    if subcmd == "scan":
        results = scan_rates()
        _display_rates(results, is_scan=True)
        return True

    if subcmd == "snapshot":
        results = get_snapshot()
        _display_rates(results, is_scan=False)
        return True

    error(f"Unknown log-health subcommand: {subcmd}")
    print_help()
    return True


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if wants_help(sys.argv[1:]):
        print_help()
        sys.exit(0)

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    handle_command("log-health", args)
