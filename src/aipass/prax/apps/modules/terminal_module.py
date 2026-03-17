# =================== AIPass ====================
# Name: terminal_module.py
# Description: PRAX Terminal Command
# Version: 1.1.0
# Created: 2025-11-15
# Modified: 2026-03-09
# =============================================

"""
PRAX Terminal Module

Implements the 'terminal' command using handle_command interface.
"""

import sys
from typing import List

from aipass.prax.apps.modules.logger import enable_terminal_output, disable_terminal_output, system_logger as logger
from aipass.cli.apps.modules import console, error
from aipass.prax.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection - shows connected handlers"""
    console.print()
    console.print("[bold cyan]PRAX Terminal Module[/bold cyan]")
    console.print()
    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Enable or disable terminal output for PRAX logging system")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()

    console.print("  [cyan]prax/modules/[/cyan]")
    console.print("    [dim]- logger.py[/dim] (enable_terminal_output, disable_terminal_output, system_logger)")
    console.print()

    console.print("[dim]Run 'python3 terminal_module.py --help' for usage[/dim]")
    console.print()


def print_help():
    """Drone-compliant help output - command syntax and examples"""
    console.print()
    console.print("[bold cyan]PRAX Terminal - Logger Output Control[/bold cyan]")
    console.print()

    console.print("[yellow]Available Subcommands:[/yellow]")
    console.print()
    console.print("  [cyan]enable[/cyan]")
    console.print("    Enable terminal output for PRAX logging")
    console.print()
    console.print("  [cyan]disable[/cyan]")
    console.print("    Disable terminal output for PRAX logging")
    console.print()

    console.print("[yellow]Usage Examples:[/yellow]")
    console.print()
    console.print("  [dim]# Enable terminal output[/dim]")
    console.print("  $ prax terminal enable")
    console.print()
    console.print("  [dim]# Disable terminal output[/dim]")
    console.print("  $ prax terminal disable")
    console.print()
    console.print("  [dim]# Standalone execution[/dim]")
    console.print("  $ python3 terminal_module.py enable")
    console.print()

    console.print("[dim]Commands: enable, disable[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle terminal command

    Args:
        command: Command name
        args: Command arguments (expects 'enable' or 'disable')

    Returns:
        True if command was handled
    """
    if command != 'terminal':
        return False

    if not args:
        print_introspection()
        return True

    try:
        if args[0] not in ['enable', 'disable']:
            print_help()
            return True  # Command was handled, even if validation failed

        json_handler.log_operation("terminal_command", {"action": args[0]})

        if args[0] == 'enable':
            enable_terminal_output()
            console.print("✅ Terminal output enabled")
        else:
            disable_terminal_output()
            console.print("✅ Terminal output disabled")

        return True

    except Exception as e:
        logger.error(f"Error in terminal command: {e}")
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

    # Execute terminal command with remaining args
    args = [arg for arg in sys.argv[1:] if not arg.startswith('--')]
    handled = handle_command('terminal', args)
    sys.exit(0 if handled else 1)
