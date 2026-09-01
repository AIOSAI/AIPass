# =================== AIPass ====================
# Name: wakeup_ops.py
# Description: Wake-Up Cron Operations Module
# Version: 2.1.0
# Created: 2026-03-08
# Modified: 2026-08-31
# =============================================

"""
Wake-up operations module -- facade for cron entry point.

Provides a clean module-layer interface over handler functions
used by daemon_wakeup.py.
"""

from aipass.prax import logger

from aipass.daemon.apps.handlers.json import json_handler

try:
    from aipass.cli.apps.modules.display import console
# OSError as well: an optional cross-branch import can fail on the filesystem,
# not only on absence. @cli imports clean under a dead cwd today (measured
# 2026-08-31); the guard catches the condition rather than today's measurement.
except (ImportError, OSError):
    from rich.console import Console

    console = Console()
    logger.info("Optional: aipass.cli.apps.modules.display not available, using rich.console fallback")

# =============================================
# INTROSPECTION
# =============================================


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]wakeup_ops Module[/bold cyan]")
    console.print()
    console.print("[dim]Facade for daemon_wakeup.py — notifications archived[/dim]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [dim](notifications archived — Telegram moving to skills system)[/dim]")
    console.print()


# =============================================
# DRONE ROUTING
# =============================================


def handle_command(command: str, args: list) -> bool:  # noqa: ARG001
    """Handle commands routed by the entry point."""
    if command == "wakeup-ops":
        if not args:
            print_introspection()
            return True
        if args[0] in ("--help", "-h", "help"):
            print_introspection()
            return True
        json_handler.log_operation("wakeup_ops_status")
        console.print()
        console.print("[bold cyan]Wakeup Ops[/bold cyan] - Cron wake-up facade")
        console.print()
        console.print("  [dim]Notifications:[/dim] archived (Telegram moving to skills system)")
        console.print()
        console.print("[dim]This module is a facade used by daemon_wakeup.py.[/dim]")
        console.print()
        return True
    return False
