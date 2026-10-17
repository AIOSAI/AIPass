# =================== AIPass ====================
# Name: watch.py
# Description: Memory Watcher Module
# Version: 0.2.0
# Created: 2026-08-13
# Modified: 2026-10-17
# =============================================

"""
Memory Watcher Module

No-args prints introspection and THEN starts the watcher: README, entry-point
help and operator habit rely on bare `watch` starting it.
"""

import os
import sys
import signal
from typing import List

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from rich.panel import Panel
from rich import box

from aipass.prax import logger
from aipass.cli.apps.modules import console, error
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help
from aipass.memory.apps.handlers.monitor.watch_runner import (
    start_watching,
    stop_watching,
    current_stats,
    wait_forever,
)


def handle_command(command: str, args: List[str]) -> bool:
    """Handle the watch command with seedgo-compliant introspection."""
    # The entry point may still send top-level help here.
    if command in ("--help", "-h", "help"):
        print_help()
        return True

    if command == "watch":
        # A help flag anywhere on the line is a question, never an instruction:
        # this command starts a process that runs until Ctrl+C.
        if wants_help(args):
            print_help()
            return True

        if not args:
            print_introspection()
            _start_session()
            return True

        # Fail loudly rather than start a long-running process nobody asked for.
        error(
            f"Unknown argument: {args[0]}",
            suggestion="Run 'drone @memory watch' to start the watcher, or 'drone @memory watch --help'",
        )
        logger.warning(f"[watch] Rejected invocation with unknown argument: {args[0]}")
        json_handler.log_operation("watch_rejected", {"argument": args[0], "args": args})
        return True

    return False


def _start_session() -> None:
    """Run a watch session: start the watcher, report it, block until Ctrl+C."""

    def signal_handler(sig, frame):
        """Handle SIGINT for graceful watcher shutdown."""
        console.print("\n")
        console.print("[dim]Stopping watcher...[/dim]")
        stop_watching()
        console.print("[green]>[/green] Watcher stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Watch Mode[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    result = start_watching()

    if not result.get("success"):
        error(f"Failed to start watcher: {result.get('error')}")
        return

    console.print(f"[green]>[/green] Watching {result.get('count', 0)} branch directories")
    console.print("[dim]Auto-rollover enabled when files exceed limits[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    stats = current_stats()
    if stats.get("success"):
        ready = stats.get("files_ready", 0)
        total = stats.get("files_checked", 0)
        status_marker = "[red]![/red]" if ready > 0 else "[green]OK[/green]"
        console.print(f"{status_marker} Current: {total} files monitored, {ready} ready for rollover")
        console.print()

    console.print("[dim]Watcher active. Waiting for file changes...[/dim]")
    wait_forever()


def print_introspection() -> None:
    """Display module introspection info (seedgo standard); also the watcher's banner."""
    console.print()
    console.print("[bold cyan]watch Module[/bold cyan]")
    console.print("Starts the auto-rollover watcher over every registered branch")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/monitor/[/cyan]  [dim]watch_runner.py, memory_watcher.py, detector.py[/dim]")
    console.print()


def print_help() -> None:
    """Display watch module help."""
    console.print()
    console.print("[bold cyan]Watch Module - Auto-Rollover Watcher[/bold cyan]")
    console.print()
    console.print("[bold]USAGE:[/bold]")
    console.print("  drone @memory watch")
    console.print()
    console.print("[bold]COMMANDS:[/bold]")
    console.print("  [cyan]watch[/cyan]   Start the watcher (runs until Ctrl+C)")
    console.print("  [cyan]help[/cyan]    Show this help message")
    console.print()
    console.print("[bold]HOW IT WORKS:[/bold]")
    console.print("  1. Watch every branch directory listed in AIPASS_REGISTRY.json")
    console.print("  2. On a .trinity/ file change, re-check entry counts against limits")
    console.print("  3. Roll the oldest entries into vectors when a file is over cap")
    console.print()
    console.print("[dim]Rollover also runs automatically at every PreCompact — the watcher[/dim]")
    console.print("[dim]is for watching a live session, not a requirement for archiving.[/dim]")
    console.print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        handle_command("watch", [])
        sys.exit(0)

    if sys.argv[1] in ("--help", "-h", "help"):
        handle_command("watch", ["--help"])
        sys.exit(0)

    command = sys.argv[1]
    if not handle_command(command, sys.argv[2:]):
        error(f"Unknown command: {command}", suggestion="Run 'drone @memory watch --help' for available commands")
        sys.exit(1)
