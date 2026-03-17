# =================== AIPass ====================
# Name: wakeup_ops.py
# Description: Wake-Up Cron Operations Module
# Version: 2.0.0
# Created: 2026-03-08
# Modified: 2026-03-10
# =============================================

"""
Wake-up operations module -- facade for cron entry point.

Provides a clean module-layer interface over handler functions
used by daemon_wakeup.py.
"""

from aipass.daemon.apps.handlers.json import json_handler

try:
    from aipass.cli.apps.modules.display import console
except ImportError:
    from rich.console import Console
    console = Console()

# =============================================
# INTROSPECTION
# =============================================

def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("wakeup_ops Module")
    console.print("Facade for daemon_wakeup.py — notifications archived")
    console.print()
    console.print("Connected Handlers:")
    console.print("  (notifications archived — Telegram moving to skills system)")
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
