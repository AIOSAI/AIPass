# =================== AIPass ====================
# Name: init_module.py
# Description: PRAX Init Command
# Version: 1.0.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
PRAX Init Module

Implements the 'init' command using handle_command interface.
"""

import sys
from typing import List

from aipass.prax.apps.modules.logger import initialize_logging_system, system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.prax.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection - shows connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Init Module[/bold cyan]")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]prax/modules/[/cyan]")
    console.print("    [dim]- logger.py[/dim] (initialize_logging_system, system_logger)")
    console.print()

    console.print("[dim]Run 'python3 init_module.py --help' for usage[/dim]")
    console.print()


def print_help():
    """Drone-compliant help output - command syntax and examples"""
    console.print()
    console.print("[bold cyan]PRAX Init - Initialize Logging System[/bold cyan]")
    console.print()

    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Initialize the PRAX logging system for monitoring AIPass operations")
    console.print()

    console.print("[yellow]Usage Examples:[/yellow]")
    console.print()
    console.print("  [dim]# Initialize logging system[/dim]")
    console.print("  $ prax init")
    console.print()
    console.print("  [dim]# Standalone execution[/dim]")
    console.print("  $ python3 init_module.py")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle init command

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled
    """
    if command != 'init':
        return False

    if not args:
        print_introspection()
        return True

    try:
        json_handler.log_operation("init_command_executed", {"command": command})
        console.print("🚀 Initializing PRAX logging system...")
        initialize_logging_system()
        console.print("✅ PRAX logging system initialized")
        return True

    except Exception as e:
        logger.error(f"Error in init command: {e}")
        error(str(e))
        return True


if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    # Handle --help flag
    if '--help' in sys.argv:
        print_help()
        sys.exit(0)

    # Handle --introspect flag
    if '--introspect' in sys.argv:
        print_introspection()
        sys.exit(0)

    # Execute init command
    handled = handle_command('init', [])
    sys.exit(0 if handled else 1)
