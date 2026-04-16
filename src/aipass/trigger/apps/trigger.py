# =================== AIPass ====================
# Name: trigger.py
# Description: Entry point CLI for drone @trigger — event bus and error registry
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
TRIGGER Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
from pathlib import Path

# Standard library imports
import importlib
from typing import List, Any

# Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for formatted output
from aipass.cli.apps.modules import console, header, error

# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> List[Any]:
    """
    Auto-discover modules in modules/ directory

    Modules must implement handle_command(command: str, args: List[str]) -> bool

    Returns:
        List of module objects with handle_command function
    """
    modules = []

    if not MODULES_DIR.exists():
        logger.warning(f"[TRIGGER] Modules directory not found: {MODULES_DIR}")
        return modules

    # Discover all .py files (except __init__.py and those starting with _)
    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.trigger.apps.modules.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)

            # Check if module has handle_command function
            if hasattr(module, "handle_command"):
                modules.append(module)
                pass  # Module loaded successfully
            else:
                pass  # No handle_command() - skip silently

        except Exception as e:
            logger.error(f"[TRIGGER] Failed to load module {module_name}: {e}")

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
            logger.error(f"[TRIGGER] Module {module.__name__} error: {e}")

    return False


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================


def print_introspection(modules: List[Any]):
    """Display discovered modules when run without arguments"""
    console.print()
    console.print("[bold cyan]TRIGGER - Branch Management System[/bold cyan]")
    console.print()
    console.print("[dim]Auto-discovered module orchestration[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split(".")[-1]
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]
            console.print(f"  [cyan]•[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'drone @trigger --help' for usage information[/dim]")
    console.print()


# =============================================================================
# DRONE COMPLIANCE - HELP SYSTEM
# =============================================================================


def print_help(modules: List[Any]):
    """Display Rich-formatted help"""
    console.print()
    header("TRIGGER - Branch Management System")
    console.print()

    console.print("[dim]Auto-discovered module orchestration[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @trigger <command> [args...][/dim]")
    console.print("  [dim]drone @trigger --help[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split(".")[-1]
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split("\n")[0]

            console.print(f"  [green]{module_name:20}[/green] [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]drone @trigger <command> --help[/dim]")
    console.print()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help"""

    # Discover available modules
    modules = discover_modules()

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run with no arguments
    if len(args) == 0:
        print_introspection(modules)
        return 0

    # Show version
    if args[0] in ["--version", "-V"]:
        console.print("TRIGGER v2.2.0")
        return 0

    # Show help for explicit help flags
    if args[0] in ["--help", "-h", "help"]:
        print_help(modules)
        return 0

    # Extract command and remaining args
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Route to modules
    if route_command(command, remaining_args, modules):
        return 0
    else:
        console.print()
        error(f"Unknown command: {command}", suggestion="Run 'drone @trigger --help' for available commands")
        console.print()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"TRIGGER entry point error: {e}", exc_info=True)
        console.print(f"\n❌ Error: {e}")
        sys.exit(1)
