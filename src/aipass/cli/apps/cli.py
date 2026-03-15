# =================== AIPass ====================
# Name: cli.py
# Description: Entry point CLI for drone @cli — display service and Rich formatting
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
CLI Branch - Universal Display/Output Service Provider

PURPOSE: Provides consistent CLI display across all AIPass branches.
Similar to Prax (logging service), CLI is a service provider for output.

SERVICES PROVIDED:
- Display: headers, success/error/warning messages, sections
- Templates: Reusable output patterns (operation_start, operation_complete)
- Formatting: Tables, lists, progress indicators

ARCHITECTURE:
- apps/modules/   = PUBLIC API (what other branches import)
- apps/handlers/  = PRIVATE implementation (internal use only)
"""

import sys
import importlib
from pathlib import Path
from typing import List

# Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# Rich library components
from rich.table import Table
from rich.columns import Columns
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich import box

# CLI modules (showcasing our own services!)
from aipass.cli.apps.modules.display import console as CONSOLE, header, success, error, warning, section
from aipass.cli.apps.modules.templates import operation_start, operation_complete


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================

def get_handler_exports(handler_package_name: str) -> List[str]:
    """Get exported functions from handler package"""
    try:
        handler_module = importlib.import_module(f"aipass.cli.apps.handlers.{handler_package_name}")
        return getattr(handler_module, '__all__', [])
    except Exception:
        return []


def print_introspection():
    """
    Display discovered modules and handlers - Quick reference

    Called when cli.py runs with no arguments.
    Shows what's connected to CLI entry point (modules and handler domains).
    """
    CONSOLE.print()
    CONSOLE.print("[bold cyan]CLI - Command Line Interface Branch[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("[dim]Universal Display & Output Service Provider[/dim]")
    CONSOLE.print()

    # Discover modules
    CONSOLE.print("[yellow]Discovered Modules:[/yellow] 3")
    CONSOLE.print()
    CONSOLE.print("  [cyan]•[/cyan] display")
    CONSOLE.print("  [cyan]•[/cyan] templates")
    CONSOLE.print("  [cyan]•[/cyan] console (Rich library wrapper)")
    CONSOLE.print()
    CONSOLE.print("[dim]Run 'python3 cli.py --help' for usage information[/dim]")
    CONSOLE.print()


def print_help():
    """Display Rich-formatted help - CLI services showcase!

    Demonstrates:
    - How to import and use CLI modules
    - Rich formatting patterns (headers, tables, panels, columns)
    - Drone compliance with Commands line
    - Beautiful terminal presentation
    """

    CONSOLE.print()

    # =============================================================================
    # SECTION 1: MAIN HEADER
    # Demonstrates: header() function from cli.apps.modules.display
    # =============================================================================
    header("CLI - Display & Templates Service Provider")

    CONSOLE.print("[dim]Universal display and output formatting for all AIPass branches[/dim]")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 2: WHAT IS CLI?
    # Demonstrates: Rich text styling with [bold], [cyan], [green], etc.
    # =============================================================================
    CONSOLE.print("[bold cyan]WHAT IS CLI?[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("CLI is the [bold]Display & Templates Service[/bold] - like Prax for logging:")
    CONSOLE.print("  [green]✓[/green] Centralized display formatting (headers, tables, panels)")
    CONSOLE.print("  [green]✓[/green] Reusable templates for common operations")
    CONSOLE.print("  [green]✓[/green] Rich library integration for beautiful output")
    CONSOLE.print("  [green]✓[/green] Consistent styling across all AIPass branches")
    CONSOLE.print()
    CONSOLE.print("Update CLI once → All branches instantly benefit from improvements")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 3: PUBLIC SERVICES
    # Demonstrates: Table() from rich.table with columns, styling
    # =============================================================================
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
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 4: IMPORT EXAMPLES
    # Demonstrates: Code examples with [dim] styling and [yellow] for labels
    # =============================================================================
    CONSOLE.print("[bold cyan]HOW TO IMPORT CLI SERVICES:[/bold cyan]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Display functions:[/yellow]")
    CONSOLE.print("[dim]  from aipass.cli.apps.modules.display import header, success, error, warning[/dim]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Templates:[/yellow]")
    CONSOLE.print("[dim]  from aipass.cli.apps.modules.templates import operation_start, operation_complete[/dim]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Rich console:[/yellow]")
    CONSOLE.print("[dim]  from rich.console import Console[/dim]")
    CONSOLE.print("[dim]  CONSOLE = Console()  # Access Rich library directly[/dim]")
    CONSOLE.print()

    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 5: USAGE EXAMPLES
    # Demonstrates: Columns() for side-by-side layout
    # =============================================================================
    CONSOLE.print("[bold cyan]USAGE EXAMPLES:[/bold cyan]")
    CONSOLE.print()

    example_cols = [
        "[yellow]Display header:[/yellow]\n[dim]header('Create Branch',\n  {'Name': 'feature',\n   'Type': 'module'})[/dim]",
        "[yellow]Show success:[/yellow]\n[dim]success('Files created',\n  items=12,\n  time='2.3s')[/dim]",
        "[yellow]Show error:[/yellow]\n[dim]error('Path not found',\n  suggestion='Check spelling')[/dim]"
    ]

    CONSOLE.print(Columns(example_cols, equal=True, expand=True))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 6: ARCHITECTURE
    # Demonstrates: Panel() for highlighted content blocks
    # =============================================================================
    CONSOLE.print("[bold cyan]ARCHITECTURE:[/bold cyan]")
    CONSOLE.print()

    arch_text = """[bold]CLI Branch Structure:[/bold]

[green]✓[/green] apps/modules/       = PUBLIC API (what branches import)
  - display.py          Display functions (header, success, error, etc.)
  - templates.py        Standard operation patterns

[green]✓[/green] apps/handlers/      = PRIVATE (internal implementation)
  - display/            Header, message formatters
  - templates/          Operation patterns

[green]✓[/green] Rich library        = Underlying formatting engine
  - Console, Table, Panel, Columns, Text styling"""

    CONSOLE.print(Panel(arch_text, border_style="green", padding=(1, 2), box=box.ROUNDED))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 8: FOR BRANCHES USING CLI
    # Demonstrates: Service provider pattern explanation
    # =============================================================================
    CONSOLE.print("[bold cyan]FOR BRANCHES USING CLI:[/bold cyan]")
    CONSOLE.print()

    workflow_text = """[bold]Replace custom display code with CLI imports:[/bold]

  [green]✓[/green] Displaying headers?         → [dim]from aipass.cli.apps.modules.display import header[/dim]
  [green]✓[/green] Showing success/errors?     → [dim]from aipass.cli.apps.modules.display import success, error[/dim]
  [green]✓[/green] Operation templates?        → [dim]from aipass.cli.apps.modules.templates import operation_*[/dim]
  [green]✓[/green] Rich formatting?            → [dim]from rich.console import Console[/dim]

[bold]Benefits:[/bold]
  • No code duplication across branches
  • Consistent formatting system-wide
  • Update CLI once → affects all branches instantly
  • Rich library integration done once, used everywhere"""

    CONSOLE.print(Panel(workflow_text, border_style="green", padding=(1, 2), box=box.ROUNDED))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 9: QUICK REFERENCE
    # Demonstrates: Using both CONSOLE.print() and module functions
    # =============================================================================
    CONSOLE.print("[bold cyan]QUICK REFERENCE:[/bold cyan]")
    CONSOLE.print()

    quick_ref = Table(show_header=True, header_style="bold cyan", border_style="dim")
    quick_ref.add_column("Task", style="green")
    quick_ref.add_column("CLI Function", style="yellow")
    quick_ref.add_column("Example", style="dim")

    quick_ref.add_row(
        "Display title",
        "header()",
        "header('Task Complete')"
    )
    quick_ref.add_row(
        "Success message",
        "success()",
        "success('Created', items=5)"
    )
    quick_ref.add_row(
        "Error message",
        "error()",
        "error('Failed', suggestion='Retry')"
    )
    quick_ref.add_row(
        "Warning message",
        "warning()",
        "warning('Be careful')"
    )
    quick_ref.add_row(
        "Section break",
        "section()",
        "section('Results')"
    )
    quick_ref.add_row(
        "Operation start",
        "operation_start()",
        "operation_start('Process', count=10)"
    )
    quick_ref.add_row(
        "Operation end",
        "operation_complete()",
        "operation_complete(created=5, failed=0)"
    )

    CONSOLE.print(quick_ref)
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 10: FULL DOCUMENTATION
    # =============================================================================
    CONSOLE.print("[bold cyan]FULL DOCUMENTATION:[/bold cyan]")
    CONSOLE.print()
    _cli_root = Path(__file__).resolve().parents[1]  # cli.py -> apps -> cli
    CONSOLE.print(f"  [yellow]Source code:[/yellow]        [dim]{_cli_root / 'apps'}[/dim]")
    CONSOLE.print(f"  [yellow]Public API:[/yellow]         [dim]{_cli_root / 'apps' / 'modules'}[/dim]")
    CONSOLE.print(f"  [yellow]Implementation:[/yellow]     [dim]{_cli_root / 'apps' / 'handlers'}[/dim]")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 11: RICH FORMATTING TIPS
    # This section itself demonstrates Rich formatting!
    # =============================================================================
    CONSOLE.print("[bold cyan]RICH FORMATTING TIPS:[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("  [yellow]Text styles:[/yellow]      [bold]bold[/bold], [dim]dim[/dim], [italic]italic[/italic], [underline]underline[/underline]")
    CONSOLE.print("  [yellow]Colors:[/yellow]           [red]red[/red], [green]green[/green], [yellow]yellow[/yellow], [blue]blue[/blue], [cyan]cyan[/cyan]")
    CONSOLE.print("  [yellow]Icons:[/yellow]            ✓ ✅ ❌ ⚠️  ⚙️  → • — ─")
    CONSOLE.print("  [yellow]Structures:[/yellow]       Table, Panel, Columns, Text, Progress")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =============================================================================
    # SECTION 12: DRONE COMPLIANCE
    # CRITICAL: Commands line must be present for drone discovery
    # =============================================================================
    CONSOLE.print("[dim]Commands: help, --help, -h[/dim]")
    CONSOLE.print()


def show_version():
    """Print version from META DATA HEADER."""
    CONSOLE.print("CLI v0.2.0")


def _handle_aipass(args):
    """Route aipass subcommands."""
    if not args:
        error("Missing subcommand", suggestion="Try: drone @cli aipass init")
        sys.exit(1)

    subcmd = args[0]
    sub_args = args[1:]

    from aipass.cli.apps.modules.init_project import handle_command
    if handle_command(subcmd, sub_args):
        return

    error(f"Unknown aipass subcommand: {subcmd}", suggestion="Try: drone @cli aipass init")
    sys.exit(1)


def main():
    """CLI branch entry point - shows available services"""

    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        return

    # Handle version flag
    if len(sys.argv) > 1 and sys.argv[1] in ['--version', '-V']:
        show_version()
        return

    # Handle help flags
    if len(sys.argv) > 1 and sys.argv[1] in ['--help', '-h', 'help']:
        print_help()
        return

    # Route subcommands
    command = sys.argv[1]
    cmd_args = sys.argv[2:] if len(sys.argv) > 2 else []

    if command == "aipass":
        _handle_aipass(cmd_args)
        return

    # Unknown command
    error(f"Unknown command: {command}", suggestion="Run 'drone @cli --help' for usage")
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        CONSOLE.print("\n[yellow]Operation cancelled[/yellow]")
        sys.exit(0)
    except Exception as e:
        logger.error(f"CLI error: {e}", exc_info=True)
        CONSOLE.print(f"\n[red]❌ Error: {e}[/red]")
        sys.exit(1)
