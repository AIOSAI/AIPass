# =================== AIPass ====================
# Name: cli.py
# Description: Entry point for drone @cli — seedgo-compliant module discovery and routing
# Version: 2.1.1
# Created: 2026-03-08
# Modified: 2026-08-11
# =============================================

"""
CLI Branch - Universal Display/Output Service Provider

Routes commands to auto-discovered modules via seedgo pattern.
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
from rich.panel import Panel
from rich import box

# CLI modules (showcasing our own services!)
from aipass.cli.apps.modules.display import console, header, error

VERSION = "2.1.0"
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
    command_modules = [m for m in modules if getattr(m, "__name__", "").split(".")[-1] not in SERVICE_MODULES]
    service_modules = [m for m in modules if getattr(m, "__name__", "").split(".")[-1] in SERVICE_MODULES]

    console.print()
    console.print("[bold cyan]CLI - Command Line Interface Branch[/bold cyan]")
    console.print(f"  Version: {VERSION}")
    console.print()
    console.print("[dim]Universal Display & Output Service Provider[/dim]")
    console.print()

    # Discovered command modules
    console.print(f"[yellow]Discovered Modules:[/yellow] {len(command_modules)}")
    for module in command_modules:
        name = getattr(module, "__name__", "unknown").split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        console.print(f"  [cyan]\u2022[/cyan] {name} \u2014 {desc}")
    if not command_modules:
        console.print("  [dim]No command modules discovered[/dim]")
    console.print()

    # Service modules (import-only, but with utility commands)
    if service_modules:
        console.print(f"[yellow]Services:[/yellow] {len(service_modules)}")
        for module in service_modules:
            name = getattr(module, "__name__", "unknown").split(".")[-1]
            desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
            console.print(f"  [cyan]\u2022[/cyan] {name} \u2014 {desc}")
        console.print()

    console.print("[yellow]Next:[/yellow]  Explore a module")
    console.print("  [green]drone @cli display[/green]              [dim]# Display module info[/dim]")
    console.print("  [green]drone @cli display demo[/green]         [dim]# Run display showcase[/dim]")
    console.print("  [green]drone @cli --help[/green]               [dim]# Full usage guide[/dim]")
    console.print()


def print_help() -> None:
    """Display Rich-formatted help - CLI services showcase!

    Shows COMMANDS, EXAMPLES, full reference.
    Follows seedgo help pattern.
    """
    console.print()

    header("CLI - Display & Templates Service Provider")

    console.print("[dim]Universal display and output formatting for all AIPass branches[/dim]")
    console.print()
    console.print("\u2500" * 70)
    console.print()

    # Usage
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @cli <command> \\[args...][/dim]")
    console.print("  [dim]drone @cli --help[/dim]")
    console.print()
    console.print("\u2500" * 70)
    console.print()

    # What is CLI
    console.print("[bold cyan]WHAT IS CLI?[/bold cyan]")
    console.print()
    console.print("CLI is the [bold]Display & Templates Service[/bold] - like Prax for logging:")
    console.print("  [green]\u2713[/green] Centralized display formatting (headers, tables, panels)")
    console.print("  [green]\u2713[/green] Reusable templates for common operations")
    console.print("  [green]\u2713[/green] Rich library integration for beautiful output")
    console.print("  [green]\u2713[/green] Consistent styling across all AIPass branches")
    console.print()
    console.print("Update CLI once \u2192 All branches instantly benefit from improvements")
    console.print()
    console.print("\u2500" * 70)
    console.print()

    # Commands
    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    console.print("  [green]drone @cli[/green]                             [dim]# Show discovered modules[/dim]")
    console.print("  [green]drone @cli display[/green]                     [dim]# Display module info[/dim]")
    console.print("  [green]drone @cli display demo[/green]                [dim]# Run display demo[/dim]")
    console.print("  [green]drone @cli templates[/green]                   [dim]# Templates module info[/dim]")
    console.print("  [green]drone @cli templates demo[/green]              [dim]# Run templates demo[/dim]")
    console.print("  [green]drone @cli --help[/green]                      [dim]# This help message[/dim]")
    console.print()
    console.print("\u2500" * 70)
    console.print()

    # Public services
    console.print("[bold cyan]PUBLIC SERVICES (apps/modules/):[/bold cyan]")
    console.print()

    services_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    services_table.add_column("Module", style="green")
    services_table.add_column("Key Functions", style="white")
    services_table.add_column("Purpose", style="dim")

    services_table.add_row(
        "display", "header(), success(), error(), warning(), section()", "Terminal output formatting"
    )
    services_table.add_row("templates", "operation_start(), operation_complete()", "Standard operation patterns")

    console.print(services_table)
    console.print()
    console.print("\u2500" * 70)
    console.print()

    # Import examples
    console.print("[bold cyan]HOW TO IMPORT CLI SERVICES:[/bold cyan]")
    console.print()

    console.print("[yellow]Display functions:[/yellow]")
    console.print("[dim]  from aipass.cli.apps.modules.display import header, success, error, warning[/dim]")
    console.print()

    console.print("[yellow]Templates:[/yellow]")
    console.print("[dim]  from aipass.cli.apps.modules.templates import operation_start, operation_complete[/dim]")
    console.print()

    console.print("[yellow]Rich console:[/yellow]")
    console.print("[dim]  from aipass.cli.apps.modules.display import console[/dim]")
    console.print("[dim]  console.print('[bold]Hello[/bold]')  # Rich formatted output[/dim]")
    console.print()

    console.print("\u2500" * 70)
    console.print()

    # Architecture
    console.print("[bold cyan]ARCHITECTURE:[/bold cyan]")
    console.print()

    arch_text = """[bold]CLI Branch Structure:[/bold]

[green]\u2713[/green] apps/modules/       = PUBLIC API (what branches import)
  - display.py          Display functions (header, success, error, etc.)
  - templates.py        Standard operation patterns

[green]\u2713[/green] apps/handlers/      = PRIVATE (internal implementation)
  - json/               JSON file I/O and validation

[green]\u2713[/green] Rich library        = Underlying formatting engine
  - Console, Table, Panel, Columns, Text styling"""

    console.print(Panel(arch_text, border_style="green", padding=(1, 2), box=box.ROUNDED))
    console.print()
    console.print("\u2500" * 70)
    console.print()

    # Drone compliance — commands line
    console.print("[dim]Commands: display, templates, demo, --help[/dim]")
    console.print()


def show_version():
    """Print version."""
    console.print(f"CLI v{VERSION}")


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

    if remaining and remaining[0] in ["--help", "-h"]:
        for module in modules:
            if module.handle_command(command, ["--help"]):
                return 0
        print_help()
        return 0

    # Route to modules
    if route_command(command, remaining, modules):
        return 0

    error(f"Unknown command: {command}", suggestion="Run 'drone @cli --help' for usage")
    return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.warning("CLI interrupted by user")
        console.print("\n[yellow]Operation cancelled[/yellow]")
        sys.exit(0)
    except Exception as e:
        logger.error(f"CLI error: {e}", exc_info=True)
        error(str(e))
        sys.exit(1)
