# =================== AIPass ====================
# Name: shutdown_module.py
# Description: PRAX Shutdown Command
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
PRAX Shutdown Module

Implements the 'shutdown' command using handle_command interface.
"""

import sys
from typing import List

from aipass.prax.apps.modules.logger import shutdown_logging_system
from aipass.cli.apps.modules import console
from aipass.prax.apps.handlers.json import json_handler


def print_help():
    """Display module help and connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Shutdown Module[/bold cyan]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]prax/modules/[/cyan]")
    console.print("    [dim]- logger.py[/dim] (shutdown_logging_system, system_logger)")
    console.print()

    console.print("[dim]Run 'python3 shutdown_module.py --help' for usage[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle shutdown command

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled
    """
    if command != 'shutdown':
        return False

    if not args:
        print_introspection()
        return True

    json_handler.log_operation("shutdown_command_executed", {"command": command})
    console.print("🛑 Shutting down PRAX logging system...")
    shutdown_logging_system()
    console.print("✅ PRAX logging system shutdown complete")
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("shutdown_module Module")
    console.print("Implements the 'shutdown' command to cleanly stop PRAX logging system")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - logger.py (shutdown_logging_system — stops watcher, restores logger, logs shutdown)")
    console.print("    - logger.py (system_logger — auto-routing logger for module log files)")
    console.print()


if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_help()
        sys.exit(0)
