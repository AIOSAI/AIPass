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
from aipass.cli.apps.modules import console, error, warning

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
        if module_file.name.startswith("_") or module_file.name == "logger.py":
            continue

        try:
            # Import module dynamically
            module_name = f"aipass.prax.apps.modules.{module_file.stem}"
            module = importlib.import_module(module_name)

            # Check for handle_command interface
            if hasattr(module, "handle_command"):
                command_handlers.append(module.handle_command)

        except Exception as e:
            logger.warning("Failed to load module %s: %s", module_file.name, e)
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
            if module_file.name.startswith("_") or module_file.name == "logger.py":
                continue
            discovered_modules.append(module_file.stem)

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(discovered_modules)}")
    console.print()

    for module_name in sorted(discovered_modules):
        console.print(f"  [cyan]•[/cyan] {module_name}")

    console.print()
    console.print("[dim]Run 'drone @prax --help' for usage information[/dim]")
    console.print()


def print_help():
    """Rich-formatted top-level help for PRAX"""
    console.print()
    console.print("[bold cyan]PRAX - System-Wide Logging Infrastructure[/bold cyan]")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print("  [cyan]monitor[/cyan]     Mission Control - unified real-time monitoring")
    console.print("  [cyan]status[/cyan]      Show PRAX system status")
    console.print("  [cyan]log-audit[/cyan]   Audit log file sizes and health")
    console.print("  [cyan]dashboard[/cyan]   System dashboard")
    console.print()

    console.print("[yellow]Flags:[/yellow]")
    console.print("  [cyan]--help[/cyan]       Show help information")
    console.print("  [cyan]--version[/cyan]    Show version")
    console.print()

    console.print("[yellow]Examples:[/yellow]")
    console.print("  $ drone @prax monitor run")
    console.print("  $ drone @prax status")
    console.print("  $ drone @prax log-audit audit")
    console.print("  $ drone @prax dashboard")
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
            logger.error("Handler failed: %s", e)
            error(f"Handler failed: {e}")
            return False

    return False


# =============================================================================
# MAIN
# =============================================================================


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="PRAX - System-Wide Logging Infrastructure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,  # We route --help to modules when a command is given
        epilog="""
Available Commands:
  monitor     Mission Control - unified real-time monitoring
  status      Show PRAX system status
  log-audit   Audit log file sizes and health
  dashboard   System dashboard

Examples:
  drone @prax monitor run
  drone @prax status
  drone @prax dashboard
        """,
    )

    # Add command argument (optional)
    parser.add_argument("command", nargs="?", help="Command to execute")

    # Add remaining arguments for command handlers
    parser.add_argument("args", nargs="*", help="Arguments for the command")

    parser.add_argument("--help", "-h", action="store_true", dest="show_help", help="Show help information")
    parser.add_argument("--version", "-V", action="version", version="PRAX v2.0.0")

    parsed_args, remaining = parser.parse_known_args()

    # If no command provided, show introspection or top-level help
    if not parsed_args.command:
        if parsed_args.show_help:
            print_help()
        else:
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

    # Pass --help through to module handler (e.g. drone @prax monitor --help)
    if parsed_args.show_help:
        all_args = ["--help"] + all_args

    # Route command to appropriate handler
    if route_command(parsed_args.command, all_args, handlers):
        return 0
    else:
        error(f"Unknown command: {parsed_args.command}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logger.error("Unhandled error in main: %s", exc)
        sys.exit(1)
