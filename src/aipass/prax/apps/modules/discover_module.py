# =================== AIPass ====================
# Name: discover_module.py
# Description: PRAX Discover Command
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
PRAX Discover Module

Implements the 'discover' command using handle_command interface.
"""

import sys
from typing import List

from aipass.cli.apps.modules import console
from aipass.prax.apps.handlers.discovery.scanner import discover_python_modules
from aipass.prax.apps.handlers.json import json_handler


def print_help():
    """Display module help and connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Discover Module[/bold cyan]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]prax/modules/[/cyan]")
    console.print("    [dim]- logger.py[/dim] (system_logger)")
    console.print()

    console.print("  [cyan]prax/handlers/discovery/[/cyan]")
    console.print("    [dim]- scanner.py[/dim] (discover_python_modules)")
    console.print()

    console.print("[dim]Run 'python3 discover_module.py --help' for usage[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle discover command

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled
    """
    if command != 'discover':
        return False

    if not args:
        print_introspection()
        return True

    json_handler.log_operation("discover_command_executed", {"command": command})
    console.print("🔍 Discovering Python modules...")
    modules = discover_python_modules()
    console.print(f"✅ Discovered {len(modules)} modules")
    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("discover_module Module")
    console.print("Implements the 'discover' command to scan and register Python modules")
    console.print()
    console.print("Connected Handlers:")
    console.print("  modules/")
    console.print("    - logger.py (system_logger — auto-routing logger for module log files)")
    console.print("  handlers/discovery/")
    console.print("    - scanner.py (discover_python_modules — scans filesystem for Python modules)")
    console.print()


if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_help()
        sys.exit(0)
