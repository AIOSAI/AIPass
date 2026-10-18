# =================== AIPass ====================
# Name: cli.py
# Description: Entry point for drone @cli — seedgo-compliant module discovery and routing
# Version: 2.3.1
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
CLI Branch - Universal Display/Output Service Provider
"""

import sys
import importlib
from pathlib import Path
from typing import List, Any

from aipass.prax.apps.modules.logger import system_logger as logger

from rich.table import Table
from rich.panel import Panel
from rich import box

from aipass.cli.apps.modules.display import console, header, error, reset_command_state, resolve_exit

VERSION = "2.3.1"
CLI_ROOT = Path(__file__).parent
MODULES_DIR = CLI_ROOT / "modules"

# Service modules — import-only, listed separately from command modules
SERVICE_MODULES = {"display", "templates"}


def discover_modules() -> List[Any]:
    """Auto-discover CLI modules in modules/ directory."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in sorted(MODULES_DIR.glob("*.py")):
        if file_path.name.startswith("_"):
            continue

        try:
            # Import by dotted name, never from the file: a second copy of display.py
            # keeps its own failure flag, which resolve_exit never reads.
            module = importlib.import_module(f"aipass.cli.apps.modules.{file_path.stem}")
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


def print_introspection() -> None:
    """Display auto-discovered modules — seedgo-compliant introspection."""
    modules = discover_modules()

    command_modules = [m for m in modules if getattr(m, "__name__", "").split(".")[-1] not in SERVICE_MODULES]
    service_modules = [m for m in modules if getattr(m, "__name__", "").split(".")[-1] in SERVICE_MODULES]

    console.print()
    console.print("[bold cyan]CLI - Command Line Interface Branch[/bold cyan]")
    console.print(f"  Version: {VERSION}")
    console.print()
    console.print("[dim]Universal Display & Output Service Provider[/dim]")
    console.print()

    console.print(f"[yellow]Discovered Modules:[/yellow] {len(command_modules)}")
    for module in command_modules:
        name = getattr(module, "__name__", "unknown").split(".")[-1]
        desc = (module.__doc__ or "").strip().split("\n")[0] if module.__doc__ else "No description"
        console.print(f"  [cyan]\u2022[/cyan] {name} \u2014 {desc}")
    if not command_modules:
        console.print("  [dim]No command modules discovered[/dim]")
    console.print()

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
    """
    console.print()

    header("CLI - Display & Templates Service Provider")

    console.print("[dim]Universal display and output formatting for all AIPass branches[/dim]")
    console.print()
    console.print("\u2500" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @cli <command> \\[args...][/dim]")
    console.print("  [dim]drone @cli --help[/dim]")
    console.print()
    console.print("\u2500" * 70)
    console.print()

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

    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    console.print("  [green]drone @cli[/green]                             [dim]# Show discovered modules[/dim]")
    console.print("  [green]drone @cli display[/green]                     [dim]# Display module info[/dim]")
    console.print("  [green]drone @cli display demo[/green]                [dim]# Run display demo[/dim]")
    console.print("  [green]drone @cli templates[/green]                   [dim]# Templates module info[/dim]")
    console.print("  [green]drone @cli templates demo[/green]              [dim]# Run templates demo[/dim]")
    console.print(
        "  [green]drone @cli show[/green]                        [dim]# Alias of display (not display show)[/dim]"
    )
    console.print("  [green]drone @cli demo[/green]                        [dim]# Runs the display demo[/dim]")
    console.print("  [green]drone @cli --version[/green]                   [dim]# Print the version[/dim]")
    console.print("  [green]drone @cli --help[/green]                      [dim]# This help message[/dim]")
    console.print()
    console.print("\u2500" * 70)
    console.print()

    console.print("[bold cyan]PUBLIC SERVICES (apps/modules/):[/bold cyan]")
    console.print()

    services_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    services_table.add_column("Module", style="green")
    services_table.add_column("Key Functions", style="white")
    services_table.add_column("Purpose", style="dim")

    services_table.add_row(
        "display", "header(), success(), error(), warning(), section(), escape()", "Terminal output formatting"
    )
    services_table.add_row("templates", "operation_start(), operation_complete()", "Standard operation patterns")

    console.print(services_table)
    console.print()
    console.print("\u2500" * 70)
    console.print()

    console.print("[bold cyan]HOW TO IMPORT CLI SERVICES:[/bold cyan]")
    console.print()

    console.print("[yellow]Display functions:[/yellow]")
    console.print("[dim]  from aipass.cli.apps.modules.display import header, success, error, warning[/dim]")
    console.print()

    console.print("[yellow]Templates:[/yellow]")
    console.print("[dim]  from aipass.cli.apps.modules.templates import operation_start, operation_complete[/dim]")
    console.print()

    console.print("[yellow]Literal square brackets:[/yellow]")
    console.print("[dim]  from aipass.cli import escape  # for header, success, section, templates[/dim]")
    console.print("[dim]  error, warning and fatal print values literally: do not escape for them[/dim]")
    console.print()

    console.print("[yellow]Rich console:[/yellow]")
    console.print("[dim]  from aipass.cli.apps.modules.display import console[/dim]")
    console.print("[dim]  console.print('\\[bold]Hello\\[/bold]')  # Rich formatted output[/dim]")
    console.print()

    console.print("\u2500" * 70)
    console.print()

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

    console.print("[dim]Commands: display, templates, show, demo, --help[/dim]")
    console.print()


def show_version():
    """Print version."""
    console.print(f"CLI v{VERSION}")


def main() -> int:
    """Main entry point - routes to modules.

    Reset the failure flag first (else a run inherits the last verdict), then let
    resolve_exit() map the route: 0 clean, 2 refused via error(), 1 not routed.
    """
    reset_command_state()
    modules = discover_modules()
    args = sys.argv[1:]

    if not args:
        print_introspection()
        return 0

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

    handled = route_command(command, remaining, modules)
    if not handled:
        error(f"Unknown command: {command}", suggestion="Run 'drone @cli --help' for usage")

    return resolve_exit(handled)


def run_cli() -> int:
    """Run main() and map an interrupt or an unhandled crash to an exit code.

    A function, not inline in __main__, so tests can pin both codes. Cancel is 130 (128 + SIGINT).
    """
    try:
        return main()
    except KeyboardInterrupt:
        logger.warning("CLI interrupted by user")
        console.print("\n[yellow]Operation cancelled[/yellow]")
        return 130
    except Exception as e:
        logger.error(f"CLI error: {e}", exc_info=True)
        error(str(e))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.exit(run_cli())
