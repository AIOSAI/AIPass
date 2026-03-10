# =================== AIPass ====================
# Name: flow.py
# Description: Entry point CLI for drone @flow — plan lifecycle management
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Flow Branch - Main Orchestrator

Auto-discovery architecture:
- Scans modules/ directory for .py files with handle_command()
- Routes commands to discovered modules automatically
- No manual imports or routing needed
"""

# INFRASTRUCTURE IMPORT PATTERN
import sys
from pathlib import Path
_PKG_ROOT = Path(__file__).resolve().parents[2]  # flow.py → apps/ → flow/ → aipass/

# Standard library imports
import importlib
import signal
from typing import List, Any

# Handle broken pipe gracefully (e.g. output piped to head)
signal.signal(signal.SIGPIPE, signal.SIG_DFL)

# Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# CLI services for formatted output
from aipass.cli.apps.modules import console, header, success, error

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
        logger.warning(f"[FLOW] Modules directory not found: {MODULES_DIR}")
        return modules

    # Discover all .py files (except __init__.py and those starting with _)
    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):
            continue

        module_name = f"aipass.flow.apps.modules.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)

            # Check if module has handle_command function
            if hasattr(module, 'handle_command'):
                modules.append(module)
                logger.info(f"[FLOW] Loaded module: {file_path.stem}")
            else:
                logger.info(f"[FLOW] Skipped {file_path.stem} - no handle_command()")

        except Exception as e:
            logger.error(f"[FLOW] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Args:
        command: Command name (e.g., 'create', 'delete', 'list')
        args: Additional arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except BrokenPipeError:
            logger.info(f"[FLOW] Broken pipe in {module.__name__} (stdout closed early)")
            return True
        except Exception as e:
            logger.error(f"[FLOW] Module {module.__name__} error: {e}")

    return False

# =============================================================================
# MAIN
# =============================================================================

def main():
    """Main entry point - routes commands or shows help"""

    # Discover available modules
    modules = discover_modules()

    if not modules:
        logger.warning("[FLOW] No modules discovered")
        error("No modules available")
        return 1

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run with no arguments
    if len(args) == 0:
        print_introspection(modules)
        return 0

    # Show version
    if args[0] in ['--version', '-V']:
        console.print("FLOW v2.2.1")
        return 0

    # Show help for explicit help flags
    if args[0] in ['--help', '-h', 'help']:
        print_help(modules)
        return 0

    # Extract command and remaining args
    # Pattern: flow <command> <args...>
    # Example: flow create . "Subject"
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Route to modules (modules handle their own --help internally)
    if route_command(command, remaining_args, modules):
        return 0

    # Fallback: try module-specific help if command wasn't handled
    if remaining_args and remaining_args[0] in ['--help', '-h']:
        print_module_help(command, modules)
        return 0
    else:
        console.print()
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print()
        console.print("Run [dim]drone @flow --help[/dim] for available commands")
        console.print()
        return 1


def print_introspection(modules: List[Any]):
    """Display discovered modules with Rich formatting (run with no args)"""
    console.print()
    console.print("[bold cyan]Flow - PLAN Management System[/bold cyan]")
    console.print()
    console.print("[dim]Task orchestration and workflow management[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(modules)}")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split('.')[-1]
            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split('\n')[0]
            console.print(f"  [cyan]•[/cyan] {module_name:20} [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("[dim]Run 'drone @flow --help' for usage information[/dim]")
    console.print()


def print_help(modules: List[Any]):
    """Display Rich-formatted help (run with --help)"""
    console.print()
    header("Flow - PLAN Management System")
    console.print()

    console.print("[dim]Task orchestration and workflow management for AIPass[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @flow <command> [args...][/dim]")
    console.print("  [dim]drone @flow --help[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()
    console.print("[dim]Commands can be called by short name (e.g., 'create') or full name (e.g., 'create_plan')[/dim]")
    console.print()

    if modules:
        for module in modules:
            module_name = module.__name__.split('.')[-1]
            # Extract short form (before underscore if present)
            short_name = module_name.split('_')[0] if '_' in module_name else module_name

            # Get first line of docstring
            description = "No description"
            if module.__doc__:
                description = module.__doc__.strip().split('\n')[0]

            # Display both forms
            if short_name != module_name:
                console.print(f"  [green]{short_name}, {module_name:18}[/green] [dim]{description}[/dim]")
            else:
                console.print(f"  [green]{module_name:20}[/green] [dim]{description}[/dim]")
    else:
        console.print("  [dim]No modules discovered[/dim]")

    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]FPLAN EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [yellow]Create new FPLAN:[/yellow]")
    console.print("    [dim]drone @flow create . \"Implementation task\"[/dim]")
    console.print("    [dim]drone @flow create . \"subject\" master[/dim]")
    console.print()
    console.print("  [yellow]Close FPLAN:[/yellow]")
    console.print("    [dim]drone @flow close FPLAN-0042[/dim]")
    console.print()
    console.print("  [yellow]List FPLANs:[/yellow]")
    console.print("    [dim]drone @flow list[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold cyan]DPLAN EXAMPLES:[/bold cyan]")
    console.print()
    console.print("  [yellow]Create DPLAN:[/yellow]")
    console.print("    [dim]drone @flow plan create \"Topic\"[/dim]")
    console.print()
    console.print("  [yellow]List DPLANs:[/yellow]")
    console.print("    [dim]drone @flow plan list[/dim]")
    console.print("    [dim]drone @flow plan list --tag idea[/dim]")
    console.print()
    console.print("  [yellow]Close DPLAN:[/yellow]")
    console.print("    [dim]drone @flow plan close 42[/dim]")
    console.print("    [dim]drone @flow plan close --all[/dim]")
    console.print()
    console.print("  [yellow]DPLAN status:[/yellow]")
    console.print("    [dim]drone @flow plan status[/dim]")
    console.print()
    console.print("  [yellow]Sync registry:[/yellow]")
    console.print("    [dim]drone @flow plan sync[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[bold]TIP:[/bold] For module-specific help:")
    console.print("  [dim]drone @flow <command> --help[/dim]")
    console.print()


def print_module_help(command: str, modules: List[Any]):
    """Display module-specific help with Rich formatting"""
    # Try to find the module that handles this command
    target_module = None
    for module in modules:
        module_name = module.__name__.split('.')[-1]
        # Check if module name matches command (e.g., create_plan matches "create" or "create_plan")
        if command == module_name or module_name.startswith(command):
            target_module = module
            break

    if not target_module:
        console.print()
        console.print(f"[red]Unknown command: {command}[/red]")
        console.print()
        console.print("Run [dim]drone @flow --help[/dim] for available commands")
        console.print()
        return

    console.print()
    module_name = target_module.__name__.split('.')[-1]
    header(f"Flow - {module_name} Command")
    console.print()

    # Display full docstring if available
    if target_module.__doc__:
        docstring = target_module.__doc__.strip()
        console.print(f"[dim]{docstring}[/dim]")
    else:
        console.print("[dim]No documentation available[/dim]")

    console.print()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        import os
        try:
            sys.stdout.close()
        except Exception as e:
            print(f"Error: {e}")
        os._exit(0)
