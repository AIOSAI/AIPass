# =================== AIPass ====================
# Name: cli.py
# Description: Entry point for drone @cli — seedgo-compliant module discovery and routing
# Version: 2.0.0
# Created: 2026-03-08
# Modified: 2026-03-15
# =============================================

"""
CLI Branch - Universal Display/Output Service Provider

Routes commands to auto-discovered modules via seedgo pattern.
- 'aipass init /path' -> init_project module (handle_command)
- Modules auto-discovered from modules/ directory
- Service modules (display, templates) also discoverable via handle_command()

SERVICES PROVIDED:
- Display: headers, success/error/warning messages, sections
- Templates: Reusable output patterns (operation_start, operation_complete)
- Formatting: Tables, lists, progress indicators

ARCHITECTURE:
- apps/modules/   = PUBLIC API (what other branches import)
- apps/handlers/  = PRIVATE implementation (internal use only)
"""

import sys
import importlib.util
from pathlib import Path
from typing import List, Any

# Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# Rich library components
from rich.table import Table
from rich.columns import Columns
from rich.panel import Panel
from rich import box

# CLI modules (showcasing our own services!)
from aipass.cli.apps.modules.display import console as CONSOLE, header, success, error, warning, section

VERSION = "2.0.0"
CLI_ROOT = Path(__file__).parent
MODULES_DIR = CLI_ROOT / "modules"

# Service modules — import-only, listed separately from command modules
SERVICE_MODULES = {"display", "templates"}


# =============================================================================
# MODULE DISCOVERY
# =============================================================================

def discover_modules() -> List[Any]:
    """Auto-discover CLI modules in modules/ directory.

    Scans modules/*.py for files with handle_command().
    Excludes __init__.py and private files.
    Follows seedgo discovery pattern exactly.
    """
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in sorted(MODULES_DIR.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        try:
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "handle_command"):
                modules.append(module)
        except Exception as e:
            logger.error(f"[CLI] Failed to load module {file_path.stem}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to appropriate module."""
    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[CLI] Module error: {e}")
    return False


# =============================================================================
# DISPLAY
# =============================================================================

def print_introspection() -> None:
    """Display auto-discovered modules — seedgo-compliant introspection.

    Called when cli.py runs with no arguments.
    Shows command modules (with handle_command) and service modules separately.
    """
    modules = discover_modules()

    # Separate command modules from service modules
    command_modules = [m for m in modules
                       if getattr(m, "__name__", "").split(".")[-1] not in SERVICE_MODULES]
    service_modules = [m for m in modules
                       if getattr(m, "__name__", "").split(".")[-1] in SERVICE_MODULES]

    CONSOLE.print()
    CONSOLE.print("[bold cyan]CLI - Command Line Interface Branch[/bold cyan]")
    CONSOLE.print(f"  Version: {VERSION}")
    CONSOLE.print()
    CONSOLE.print("[dim]Universal Display & Output Service Provider[/dim]")
    CONSOLE.print()

    # Discovered command modules
    CONSOLE.print(f"[yellow]Discovered Modules:[/yellow] {len(command_modules)}")
    for module in command_modules:
        name = getattr(module, "__name__", "unknown").split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        CONSOLE.print(f"  [cyan]\u2022[/cyan] {name} \u2014 {desc}")
    if not command_modules:
        CONSOLE.print("  [dim]No command modules discovered[/dim]")
    CONSOLE.print()

    # Service modules (import-only, but with utility commands)
    if service_modules:
        CONSOLE.print(f"[yellow]Services:[/yellow] {len(service_modules)}")
        for module in service_modules:
            name = getattr(module, "__name__", "unknown").split(".")[-1]
            desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
            CONSOLE.print(f"  [cyan]\u2022[/cyan] {name} \u2014 {desc}")
        CONSOLE.print()

    CONSOLE.print("[yellow]Next:[/yellow]  Explore a module")
    CONSOLE.print("  [green]drone @cli aipass[/green]               [dim]# Project commands[/dim]")
    CONSOLE.print("  [green]drone @cli aipass init --help[/green]   [dim]# Bootstrap a project[/dim]")
    CONSOLE.print("  [green]drone @cli --help[/green]               [dim]# Full usage guide[/dim]")
    CONSOLE.print()


def print_help() -> None:
    """Display Rich-formatted help - CLI services showcase!

    Shows COMMANDS, EXAMPLES, full reference.
    Follows seedgo help pattern.
    """
    CONSOLE.print()

    header("CLI - Display & Templates Service Provider")

    CONSOLE.print("[dim]Universal display and output formatting for all AIPass branches[/dim]")
    CONSOLE.print()
    CONSOLE.print("\u2500" * 70)
    CONSOLE.print()

    # What is CLI
    CONSOLE.print("[bold cyan]WHAT IS CLI?[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("CLI is the [bold]Display & Templates Service[/bold] - like Prax for logging:")
    CONSOLE.print("  [green]\u2713[/green] Centralized display formatting (headers, tables, panels)")
    CONSOLE.print("  [green]\u2713[/green] Reusable templates for common operations")
    CONSOLE.print("  [green]\u2713[/green] Rich library integration for beautiful output")
    CONSOLE.print("  [green]\u2713[/green] Consistent styling across all AIPass branches")
    CONSOLE.print()
    CONSOLE.print("Update CLI once \u2192 All branches instantly benefit from improvements")
    CONSOLE.print()
    CONSOLE.print("\u2500" * 70)
    CONSOLE.print()

    # Commands
    CONSOLE.print("[bold cyan]COMMANDS:[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("  [green]drone @cli[/green]                             [dim]# Show discovered modules[/dim]")
    CONSOLE.print("  [green]drone @cli aipass[/green]                      [dim]# Project commands[/dim]")
    CONSOLE.print("  [green]drone @cli aipass init[/green]                 [dim]# Bootstrap a project[/dim]")
    CONSOLE.print("  [green]drone @cli aipass init /path MyProj[/green]    [dim]# Bootstrap with name[/dim]")
    CONSOLE.print("  [green]drone @cli display[/green]                     [dim]# Display module info[/dim]")
    CONSOLE.print("  [green]drone @cli display demo[/green]                [dim]# Run display demo[/dim]")
    CONSOLE.print("  [green]drone @cli templates[/green]                   [dim]# Templates module info[/dim]")
    CONSOLE.print("  [green]drone @cli templates demo[/green]              [dim]# Run templates demo[/dim]")
    CONSOLE.print("  [green]drone @cli --help[/green]                      [dim]# This help message[/dim]")
    CONSOLE.print()
    CONSOLE.print("\u2500" * 70)
    CONSOLE.print()

    # Public services
    CONSOLE.print("[bold cyan]PUBLIC SERVICES (apps/modules/):[/bold cyan]")
    CONSOLE.print()

    services_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    services_table.add_column("Module", style="green")
    services_table.add_column("Key Functions", style="white")
    services_table.add_column("Purpose", style="dim")

    services_table.add_row(
        "display",
        "header(), success(), error(), warning(), section()",
        "Terminal output formatting"
    )
    services_table.add_row(
        "templates",
        "operation_start(), operation_complete()",
        "Standard operation patterns"
    )

    CONSOLE.print(services_table)
    CONSOLE.print()
    CONSOLE.print("\u2500" * 70)
    CONSOLE.print()

    # Import examples
    CONSOLE.print("[bold cyan]HOW TO IMPORT CLI SERVICES:[/bold cyan]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Display functions:[/yellow]")
    CONSOLE.print("[dim]  from aipass.cli.apps.modules.display import header, success, error, warning[/dim]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Templates:[/yellow]")
    CONSOLE.print("[dim]  from aipass.cli.apps.modules.templates import operation_start, operation_complete[/dim]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Rich console:[/yellow]")
    CONSOLE.print("[dim]  from aipass.cli.apps.modules.display import console[/dim]")
    CONSOLE.print("[dim]  console.print('[bold]Hello[/bold]')  # Rich formatted output[/dim]")
    CONSOLE.print()

    CONSOLE.print("\u2500" * 70)
    CONSOLE.print()

    # Architecture
    CONSOLE.print("[bold cyan]ARCHITECTURE:[/bold cyan]")
    CONSOLE.print()

    arch_text = """[bold]CLI Branch Structure:[/bold]

[green]\u2713[/green] apps/modules/       = PUBLIC API (what branches import)
  - display.py          Display functions (header, success, error, etc.)
  - templates.py        Standard operation patterns
  - init_project.py     Project bootstrap (aipass init)

[green]\u2713[/green] apps/handlers/      = PRIVATE (internal implementation)
  - init/               Bootstrap logic (aipass init)
  - json/               JSON file I/O and validation

[green]\u2713[/green] Rich library        = Underlying formatting engine
  - Console, Table, Panel, Columns, Text styling"""

    CONSOLE.print(Panel(arch_text, border_style="green", padding=(1, 2), box=box.ROUNDED))
    CONSOLE.print()
    CONSOLE.print("\u2500" * 70)
    CONSOLE.print()

    # Drone compliance — commands line
    CONSOLE.print("[dim]Commands: aipass, display, templates, demo, --help[/dim]")
    CONSOLE.print()


def show_version():
    """Print version."""
    CONSOLE.print(f"CLI v{VERSION}")


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main() -> int:
    """Main entry point - routes to modules."""
    modules = discover_modules()
    args = sys.argv[1:]

    # No args -> introspection (discovery mode)
    if not args:
        print_introspection()
        return 0

    # Help flag -> full help with usage
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return 0

    if args[0] in ["--version", "-V"]:
        show_version()
        return 0

    command = args[0]
    remaining = args[1:] if len(args) > 1 else []

    # Route to modules
    if route_command(command, remaining, modules):
        return 0

    error(f"Unknown command: {command}", suggestion="Run 'drone @cli --help' for usage")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.warning("CLI interrupted by user")
        CONSOLE.print("\n[yellow]Operation cancelled[/yellow]")
        sys.exit(0)
    except Exception as e:
        logger.error(f"CLI error: {e}", exc_info=True)
        CONSOLE.print(f"\n[red]Error: {e}[/red]")
        sys.exit(1)
