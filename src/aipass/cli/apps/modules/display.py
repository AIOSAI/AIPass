# =================== AIPass ====================
# Name: display.py
# Description: CLI Display Module — public API for Rich terminal output formatting
# Version: 0.4.0
# Created: 2025-11-12
# Modified: 2025-11-15
# =============================================

"""
CLI Display Module - PUBLIC API

Provides display functions for all branches:
- header() - Bordered section headers
- success() - Green checkmark + message
- error() - Red X + error message
- warning() - Yellow warning + message
- fatal() - Error + sys.exit(1)
- section() - Visual section breaks

Uses Rich library for beautiful terminal output.
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, List

# Rich library
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

from aipass.cli.apps.handlers.json import json_handler

# NOTE: Cannot import prax here — circular import (prax depends on cli)
# Silent catches in this file are bypassed via .seedgo/bypass.json

# Detect if output is a TTY (interactive terminal) vs piped/redirected
# When piped, disable force_terminal to let Rich auto-detect and strip ANSI codes
_IS_TTY = sys.stdout.isatty()

# Initialize Rich console (lowercase follows service instance pattern)
CONSOLE = Console(force_terminal=_IS_TTY)  # TTY=colors, piped=plain
console = CONSOLE  # Primary export (lowercase service instance pattern)
err_console = Console(stderr=True, force_terminal=sys.stderr.isatty())  # Stderr auto-detect

# Trigger loaded lazily to avoid circular import
_TRIGGER = None
_TRIGGER_LOADED = False


# ============================================================================
# MODULE PATTERN FUNCTIONS (SEEDGO compliant)
# ============================================================================


def print_introspection():
    """Display module info and connected handlers"""
    CONSOLE.print()
    CONSOLE.print("[bold cyan]CLI Display Module[/bold cyan]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Functions:[/yellow]")
    CONSOLE.print()
    CONSOLE.print("  [cyan]header()[/cyan]      Bordered section header with optional details")
    CONSOLE.print("  [cyan]success()[/cyan]     Green checkmark message with kwargs")
    CONSOLE.print("  [cyan]error()[/cyan]       Red error with optional suggestion")
    CONSOLE.print("  [cyan]warning()[/cyan]     Yellow warning with optional details")
    CONSOLE.print("  [cyan]fatal()[/cyan]       Error + sys.exit(1)")
    CONSOLE.print("  [cyan]section()[/cyan]     Visual section separator")
    CONSOLE.print("  [cyan]console[/cyan]       Rich Console instance")
    CONSOLE.print()

    CONSOLE.print("[dim]Run 'drone @cli display --help' for usage[/dim]")
    CONSOLE.print()


def print_help():
    """Display Rich-formatted help - CLI Display Module showpiece!"""

    CONSOLE.print()

    # =========================================================================
    # RICH FORMATTING TIP: Use header() function for main titles
    # header() creates a bordered box automatically
    # =========================================================================
    header("CLI Display Module")

    CONSOLE.print()

    # RICH FORMATTING TIP: [dim] makes text appear dimmed/grayed out
    CONSOLE.print("[dim]Rich terminal output formatting for all AIPass branches[/dim]")
    CONSOLE.print()
    CONSOLE.print("─" * 70)  # Separator line (matches handler style)
    CONSOLE.print()

    # =========================================================================
    # RICH FORMATTING TIP: Match handler style - simple [bold cyan]LABEL:[/bold cyan] format
    # NO decorative borders (═══), just clean headers like handlers use
    # =========================================================================
    CONSOLE.print("[bold cyan]WHAT IS DISPLAY?[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("Display is the [bold]CLI's universal output service[/bold] that provides:")
    # RICH FORMATTING TIP: Use [green]✓[/green] for checkmarks in lists
    CONSOLE.print("  [green]✓[/green] Consistent Rich-formatted output across all branches")
    CONSOLE.print(
        "  [green]✓[/green] Six core display functions ([green]header, success, error, warning, fatal, section[/green])"
    )
    CONSOLE.print("  [green]✓[/green] Beautiful terminal output with colors, panels, and formatting")
    CONSOLE.print("  [green]✓[/green] Integration with CLI error handler for advanced error display")
    CONSOLE.print()

    # =========================================================================
    # RICH FORMATTING TIP: Tables are powerful for structured data
    # Create with Table(), add columns, add rows, then print
    # =========================================================================
    CONSOLE.print("[bold cyan]PUBLIC API FUNCTIONS (6 total):[/bold cyan]")
    CONSOLE.print()

    # RICH FORMATTING TIP: Table styling - show_header, header_style, border_style
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Function", style="green")  # Column styling
    table.add_column("Signature", style="yellow")
    table.add_column("Purpose", style="dim")

    table.add_row("header()", "title, details=None", "Bordered section headers with optional key-value details")
    table.add_row("success()", "message, **kwargs", "Success messages with green checkmark + optional details")
    table.add_row("error()", "message, suggestion=None", "Error messages with red X + optional suggestion")
    table.add_row("warning()", "message, details=None", "Warning messages with yellow symbol + optional details")
    table.add_row("fatal()", "message, suggestion=None", "Error message + sys.exit(1) for unrecoverable failures")
    table.add_row("section()", "title", "Visual section separators with title and line")

    # RICH FORMATTING TIP: Print the table after adding all rows
    CONSOLE.print(table)
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =========================================================================
    # RICH FORMATTING TIP: Columns layout for side-by-side content
    # Columns([item1, item2, item3], equal=True, expand=True)
    # =========================================================================
    CONSOLE.print("[bold cyan]USAGE:[/bold cyan]")
    CONSOLE.print()

    usage_examples = [
        "[yellow]Module Info:[/yellow]\n  [dim]drone @cli display[/dim]",
        "[yellow]Run Demo:[/yellow]\n  [dim]drone @cli display demo[/dim]",
        "[yellow]Show Help:[/yellow]\n  [dim]drone @cli display --help[/dim]",
    ]

    # RICH FORMATTING TIP: Columns creates side-by-side layout
    CONSOLE.print(Columns(usage_examples, equal=True, expand=True))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # =========================================================================
    # RICH FORMATTING TIP: Panels are good for highlighted content blocks
    # Panel(content, border_style="color", padding=(top/bottom, left/right))
    # =========================================================================
    CONSOLE.print("[bold cyan]CODE EXAMPLES:[/bold cyan]")
    CONSOLE.print()

    code_examples = """[bold]Import and use in your Python code:[/bold]

  [yellow]from aipass.cli.apps.modules.display import header, success, error, warning, section[/yellow]

  [dim]# Display section header[/dim]
  header('Create Branch', {'Name': 'new_branch', 'Type': 'module'})

  [dim]# Show success with details[/dim]
  success('Branch created successfully', items=5, time='2.3s')

  [dim]# Display error with suggestion[/dim]
  error('Branch not found', suggestion='Check branch name spelling')

  [dim]# Show warning[/dim]
  warning('Template version mismatch', details='Expected v2.1, found v2.0')

  [dim]# Create section break[/dim]
  section('Validation Results')"""

    # RICH FORMATTING TIP: Panel wraps content in a bordered box
    CONSOLE.print(Panel(code_examples, border_style="green", padding=(1, 2)))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # Simple header style (matching handlers)
    CONSOLE.print("[bold cyan]INTEGRATION:[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("  [green]✓[/green] [bold]Rich Formatting:[/bold] Beautiful terminal output with colors and styles")
    CONSOLE.print(
        "  [green]✓[/green] [bold]All Branches:[/bold] Import and use display functions for consistent output"
    )
    CONSOLE.print("  [green]✓[/green] [bold]Rich Library:[/bold] Built on Rich for beautiful terminal formatting")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # Simple header style (matching handlers)
    CONSOLE.print("[bold cyan]REFERENCE:[/bold cyan]")
    CONSOLE.print()
    # RICH FORMATTING TIP: Use [yellow] for labels, [dim] for paths
    _display_path = Path(__file__).resolve()
    _cli_root = _display_path.parents[2]  # display.py -> modules -> apps -> cli
    CONSOLE.print(f"  [yellow]Module:[/yellow]      [dim]{_display_path}[/dim]")
    CONSOLE.print(f"  [yellow]Handlers:[/yellow]    [dim]{_cli_root / 'apps' / 'handlers' / 'display'}[/dim]")
    CONSOLE.print("  [yellow]Standards:[/yellow]   [dim]See CODE_STANDARDS/cli.md[/dim]")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # RICH FORMATTING TIP: Use [bold] for emphasis without color
    CONSOLE.print("[bold]TIP:[/bold] Run [green]drone @cli display demo[/green] to see all functions in action!")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # RICH FORMATTING TIP: Commands line required for drone discovery
    # This is how drone finds available commands - keep [dim] style
    CONSOLE.print("[dim]Commands: display, show, demo, --help[/dim]")
    CONSOLE.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle module commands"""
    if command == "demo":
        run_demo()
        return True
    if command not in ("display", "show"):
        return False
    if not args:
        print_introspection()
        return True
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True
    if args[0] == "demo":
        run_demo()
        return True
    return False


def run_demo():
    """Run display function demonstrations"""
    CONSOLE.print()
    header("CLI Display Module - Demo")

    CONSOLE.print("[bold]Display functions with Rich formatting:[/bold]")
    CONSOLE.print()

    # Demo success
    success("Operation completed successfully", items=5, time="2.3s")
    CONSOLE.print()

    # Demo warning
    warning("Template version mismatch", details="Expected v2.1, found v2.0")
    CONSOLE.print()

    # Demo error
    error("Cannot create virtual environment", suggestion="sudo apt install python3-venv")
    CONSOLE.print()

    # Demo section
    section("Summary")
    CONSOLE.print("  ✅ 3 operations succeeded")
    CONSOLE.print("  ⚠️  1 warning")
    CONSOLE.print("  ❌ 1 error")
    CONSOLE.print()

    CONSOLE.print("[bold green]✨ Rich library integration complete![/bold green]")
    CONSOLE.print("[dim]All display functions now use Rich for beautiful terminal output[/dim]")

    json_handler.log_operation("display_demo")

    CONSOLE.print()


# ============================================================================
# PUBLIC API FUNCTIONS (Keep existing - don't break compatibility)
# ============================================================================


def header(title: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    Display bordered section header using Rich Panel

    Args:
        title: Header title
        details: Optional key-value pairs to display

    Example:
        header('Create Branch', {'Name': 'new_branch', 'Type': 'module'})
    """
    CONSOLE.print(Panel(f"[bold cyan]{title}[/bold cyan]", expand=False))
    if details:
        CONSOLE.print()
        for key, value in details.items():
            CONSOLE.print(f"  [dim]{key}:[/dim] {value}")
    # Fire trigger event for header display (lazy load to avoid circular import)
    global _TRIGGER, _TRIGGER_LOADED
    if not _TRIGGER_LOADED:
        _TRIGGER_LOADED = True
        try:
            from aipass.trigger.apps.modules.core import trigger as t

            _TRIGGER = t
        except ImportError:
            pass
    if _TRIGGER:
        _TRIGGER.fire("cli_header_displayed", title=title)
    CONSOLE.print()


def success(message: str, **kwargs) -> None:
    """
    Display success message with Rich styling

    Args:
        message: Success message
        **kwargs: Optional details to display

    Example:
        success('Branch created', items=5, time='2.3s')
    """
    CONSOLE.print(f"✅ [green]{message}[/green]")
    for key, value in kwargs.items():
        CONSOLE.print(f"   [dim]{key}: {value}[/dim]")


def error(message: str, suggestion: str | None = None) -> None:
    """
    Display error message with Rich styling

    Args:
        message: Error message
        suggestion: Optional suggestion for fixing

    Example:
        error('Branch not found', suggestion='Check branch name spelling')
    """
    err_console.print(f"❌ [red bold]{message}[/red bold]")
    if suggestion:
        err_console.print(f"   [yellow]→ Try: {suggestion}[/yellow]")


def warning(message: str, details: str | None = None) -> None:
    """
    Display warning message with Rich styling

    Args:
        message: Warning message
        details: Optional additional details

    Example:
        warning('Branch already exists, skipping')
    """
    err_console.print(f"⚠️  [yellow]{message}[/yellow]")
    if details:
        err_console.print(f"   [dim]{details}[/dim]")


def fatal(message: str, suggestion: str | None = None) -> None:
    """
    Display error message with Rich styling and exit with code 1

    Like error() but terminates the process. Use for unrecoverable failures.

    Args:
        message: Error message
        suggestion: Optional suggestion for fixing

    Example:
        fatal('Config file missing', suggestion='Run aipass init first')
    """
    err_console.print(f"❌ [red bold]{message}[/red bold]")
    if suggestion:
        err_console.print(f"   [yellow]→ Try: {suggestion}[/yellow]")
    sys.exit(1)


def section(title: str) -> None:
    """
    Display section separator with Rich styling

    Args:
        title: Section title

    Example:
        section('Validation Results')
    """
    CONSOLE.print()
    CONSOLE.print(f"[bold]{title}[/bold]")
    CONSOLE.print("─" * 50)


# ============================================================================
# MODULE EXPORTS
# ============================================================================

# Note: __all__ uses lowercase by convention (Python standard library pattern)
__all__ = [
    "console",  # Primary export (service instance pattern)
    "CONSOLE",  # Internal constant (kept for backward compatibility)
    "err_console",  # Stderr console for error/warning output
    "header",
    "success",
    "error",
    "warning",
    "fatal",
    "section",
]

# ============================================================================
# ENTRY POINT (SEEDGO pattern)
# ============================================================================

if __name__ == "__main__":
    try:
        # Show introspection when run without arguments
        if len(sys.argv) == 1:
            print_introspection()
            sys.exit(0)

        # Handle help flag (drone compliance)
        if sys.argv[1] in ["--help", "-h", "help"]:
            print_help()
            sys.exit(0)

        # Route commands
        command = sys.argv[1]
        args = sys.argv[2:] if len(sys.argv) > 2 else []

        if handle_command(command, args):
            sys.exit(0)
        else:
            CONSOLE.print(f"[red]Unknown command: {command}[/red]")
            CONSOLE.print("[dim]Run 'drone @cli display --help' for usage[/dim]")
            sys.exit(1)
    except Exception as e:
        CONSOLE.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
