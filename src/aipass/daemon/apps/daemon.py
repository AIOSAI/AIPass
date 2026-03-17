# =================== AIPass ====================
# Name: daemon.py
# Description: Entry point CLI for drone @daemon
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
DAEMON Branch - Main Orchestrator

Explicit module imports:
- Imports known modules from modules/ directory
- Routes commands to discovered modules automatically
"""

# Standard library imports
import sys
from typing import List, Any

# Logger
from aipass.prax.apps.modules.logger import system_logger as logger

# Console
from aipass.cli.apps.modules import console, error
from aipass.daemon.apps.handlers.json import json_handler

def _header(text):
    console.print(f"\n[bold cyan]{'='*70}[/bold cyan]")
    console.print(f"[bold cyan]  {text}[/bold cyan]")
    console.print(f"[bold cyan]{'='*70}[/bold cyan]")

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

from aipass.daemon.apps.modules import update, schedule, activity_report, actions

def get_modules() -> List[Any]:
    """
    Return list of known modules that implement handle_command().

    Returns:
        List of module objects with handle_command function
    """
    modules = []
    for mod in [update, schedule, activity_report, actions]:
        if hasattr(mod, 'handle_command'):
            modules.append(mod)
    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Args:
        command: Command name (e.g., 'create', 'update', 'list')
        args: Additional arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[DAEMON] Module {module.__name__} error: {e}")

    return False

# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================

def print_introspection(modules: List[Any]):
    """Display discovered modules when run without arguments"""
    console.print()
    console.print("[bold cyan]DAEMON - Branch Management System[/bold cyan]")
    console.print()
    console.print("[dim]Module orchestration[/dim]")
    console.print()

    console.print(f"[yellow]Modules:[/yellow] {len(modules)}")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split('.')[-1]
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split('\n')[0]
            console.print(f"  [cyan]*[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'daemon --help' for usage information[/dim]")
    console.print()


# =============================================================================
# DRONE COMPLIANCE - HELP SYSTEM
# =============================================================================

def print_help(modules: List[Any]):
    """Display Rich-formatted help"""
    console.print()
    _header("DAEMON - Branch Management System")
    console.print()

    console.print("[dim]Module orchestration[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]daemon <command> [args...][/dim]")
    console.print("  [dim]daemon --help[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    # Show actual routable commands, not module names
    _COMMAND_HELP = [
        ("update", "Returns digest of DAEMON activity for check-ins."),
        ("schedule", "CLI interface for fire-and-forget scheduled follow-ups."),
        ("activity", "Quick 24-hour activity summary."),
        ("activity-report", "Full detailed activity report (--json for raw)."),
        ("branch-health", "Single branch deep dive (e.g., branch-health DAEMON)."),
        ("actions", "CLI interface for the numbered action registry."),
    ]

    for cmd_name, desc in _COMMAND_HELP:
        console.print(f"  [green]{cmd_name:20}[/green] [dim]{desc}[/dim]")

    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]daemon <command> --help[/dim]")
    console.print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point - routes commands or shows help"""

    # Get available modules
    modules = get_modules()

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run with no arguments
    if len(args) == 0:
        print_introspection(modules)
        return 0

    # Version flag
    if args[0] in ['--version', '-V']:
        console.print("DAEMON v1.0.0")
        return 0

    # Show help for explicit help flags
    if args[0] in ['--help', '-h', 'help']:
        print_help(modules)
        return 0

    # Extract command and remaining args
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    json_handler.log_operation("daemon_command", {"command": command})

    # Route to modules
    if route_command(command, remaining_args, modules):
        return 0
    else:
        console.print()
        error(f"Unknown command: {command}", suggestion="Run 'daemon --help' for available commands")
        console.print()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"DAEMON entry point error: {e}", exc_info=True)
        console.print(f"\nError: {e}")
        sys.exit(1)
