# =================== AIPass ====================
# Name: prax.py
# Description: Entry point CLI for drone @prax — logging, monitoring, dashboard
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
PRAX Branch - Main Orchestrator

Auto-discovers command modules and routes commands to them.
Entry point contains no business logic - modules implement functionality.
"""

import sys
from pathlib import Path

# Standard library imports
import argparse
import importlib
from typing import List, Callable

# Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services
from aipass.cli.apps.modules import console, header, success, error, warning

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

def discover_command_modules() -> List[Callable]:
    """
    Auto-discover command modules from modules/ directory

    Each module must implement:
        handle_command(command: str, args: List[str]) -> bool

    Returns:
        List of handle_command functions from discovered modules
    """
    command_handlers = []
    modules_dir = Path(__file__).parent / "modules"

    if not modules_dir.exists():
        return command_handlers

    # Scan for Python files in modules directory
    for module_file in modules_dir.glob("*.py"):
        # Skip __init__.py and non-command modules
        if module_file.name.startswith('_') or module_file.name == 'logger.py':
            continue

        try:
            # Import module dynamically
            module_name = f"aipass.prax.apps.modules.{module_file.stem}"
            module = importlib.import_module(module_name)

            # Check for handle_command interface
            if hasattr(module, 'handle_command'):
                command_handlers.append(module.handle_command)

        except Exception as e:
            warning(f"Failed to load module {module_file.name}: {e}")

    return command_handlers

# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================

def print_introspection():
    """Display discovered modules (main entry point - modules only, no handlers)"""
    console.print()
    console.print("[bold cyan]PRAX - System-Wide Logging Infrastructure[/bold cyan]")
    console.print()
    console.print("[dim]Unified logging system for AIPass ecosystem[/dim]")
    console.print()

    # Discover modules
    modules_dir = Path(__file__).parent / "modules"
    discovered_modules = []

    if modules_dir.exists():
        for module_file in modules_dir.glob("*.py"):
            if module_file.name.startswith('_') or module_file.name == 'logger.py':
                continue
            discovered_modules.append(module_file.stem)

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(discovered_modules)}")
    console.print()

    for module_name in sorted(discovered_modules):
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'prax --help' for usage information[/dim]")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================

def route_command(command: str, args: List[str], handlers: List[Callable]) -> bool:
    """
    Route command to appropriate module handler

    Args:
        command: Command name
        args: Command arguments
        handlers: List of command handler functions

    Returns:
        True if command was handled, False otherwise
    """
    for handler in handlers:
        try:
            if handler(command, args):
                return True
        except Exception as e:
            error(f"Handler failed: {e}")
            return False

    return False

# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='PRAX - System-Wide Logging Infrastructure',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Commands:
  monitor     Mission Control - unified real-time monitoring
  init        Initialize PRAX logging system
  status      Show PRAX system status
  run         Start continuous logging mode
  shutdown    Shutdown PRAX logging system
  discover    Discover Python modules in ecosystem
  terminal    Enable/disable terminal output (requires: enable|disable)

Examples:
  prax monitor
  prax init
  prax status
  prax terminal enable
        """
    )

    # Add command argument (optional)
    parser.add_argument('command',
                       nargs='?',
                       help='Command to execute')

    # Add remaining arguments for command handlers
    parser.add_argument('args',
                       nargs='*',
                       help='Arguments for the command')

    parser.add_argument('--version', '-V', action='version', version='PRAX v2.0.0')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    parsed_args, remaining = parser.parse_known_args()

    # If no command provided, show introspection display
    if not parsed_args.command:
        print_introspection()
        return 0

    # Discover command modules
    handlers = discover_command_modules()

    if not handlers:
        error("No command modules discovered")
        return 1

    # Merge positional args with any flags argparse didn't consume
    # so subcommand handlers like dashboard can receive --all, --branch, etc.
    all_args = parsed_args.args + remaining

    # Route command to appropriate handler
    if route_command(parsed_args.command, all_args, handlers):
        return 0
    else:
        error(f"Unknown command: {parsed_args.command}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
