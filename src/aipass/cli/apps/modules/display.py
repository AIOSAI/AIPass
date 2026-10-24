# =================== AIPass ====================
# Name: display.py
# Description: CLI Display Module — public API for Rich terminal output formatting
# Version: 0.5.4
# Created: 2025-11-12
# Modified: 2026-10-24
# =============================================

"""
CLI Display Module - PUBLIC API
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, List

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.markup import escape  # published, bound not wrapped: docs/rich_markup.md says which functions need it

from aipass.cli.apps.handlers.json import json_handler
from aipass.cli.apps.handlers.cli.help_flags import wants_help

# No prax logger: circular import (prax depends on cli).


class _LiveConsole(Console):
    """A Console that decides colour at each print, against the live stream.

    Rich fixes its colour system once in __init__; an import-time answer goes stale
    when the stream changes (pytest capture), so it is re-detected on every read.
    """

    @property
    def _color_system(self):
        """The colour system for the stream as it is now, or None for a pipe or capture."""
        return self._detect_color_system()

    # Rich declares _color_system as an attribute; replacing it with a property is the cure.
    @_color_system.setter
    def _color_system(self, _value) -> None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Console.__init__ assigns its import-time answer here; it is not kept."""


CONSOLE = _LiveConsole()  # terminal=colour, pipe or capture=plain, decided per print
console = CONSOLE  # Primary export (lowercase service instance pattern)
err_console = _LiveConsole(stderr=True)  # same, against the live sys.stderr

# shortcut: inert, read by nothing; kept because other branches' conftests monkeypatch them; drop once they stop.
_TRIGGER = None
_TRIGGER_LOADED = False

_CMD_STATE = {"failed": False}


def mark_command_failed() -> None:
    """Set the process-level failure flag (called automatically by error())."""
    _CMD_STATE["failed"] = True


def command_failed() -> bool:
    """Return whether mark_command_failed() has been called since last reset."""
    return _CMD_STATE["failed"]


def reset_command_state() -> None:
    """Reset the failure flag to False (for tests and main() entry)."""
    _CMD_STATE["failed"] = False


def resolve_exit(handled: bool) -> int:
    """Map handled/failed state to an exit code: 1 not handled, 2 failed, 0 clean."""
    if not handled:
        return 1
    if _CMD_STATE["failed"]:
        return 2
    return 0


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

    header("CLI Display Module")

    CONSOLE.print()

    CONSOLE.print("[dim]Rich terminal output formatting for all AIPass branches[/dim]")
    CONSOLE.print()
    CONSOLE.print("─" * 70)  # Separator line (matches handler style)
    CONSOLE.print()

    CONSOLE.print("[bold cyan]WHAT IS DISPLAY?[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("Display is the [bold]CLI's universal output service[/bold] that provides:")
    CONSOLE.print("  [green]✓[/green] Consistent Rich-formatted output across all branches")
    CONSOLE.print(
        "  [green]✓[/green] Six core display functions ([green]header, success, error, warning, fatal, section[/green])"
    )
    CONSOLE.print("  [green]✓[/green] Beautiful terminal output with colors, panels, and formatting")
    CONSOLE.print()

    CONSOLE.print("[bold cyan]PUBLIC API FUNCTIONS (6 total):[/bold cyan]")
    CONSOLE.print()

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

    CONSOLE.print(table)
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    CONSOLE.print("[bold cyan]USAGE:[/bold cyan]")
    CONSOLE.print()

    usage_examples = [
        "[yellow]Module Info:[/yellow]\n  [dim]drone @cli display[/dim]",
        "[yellow]Run Demo:[/yellow]\n  [dim]drone @cli display demo[/dim]",
        "[yellow]Show Help:[/yellow]\n  [dim]drone @cli display --help[/dim]",
    ]

    CONSOLE.print(Columns(usage_examples, equal=True, expand=True))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

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

    CONSOLE.print(Panel(code_examples, border_style="green", padding=(1, 2)))
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

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

    CONSOLE.print("[bold cyan]REFERENCE:[/bold cyan]")
    CONSOLE.print()
    # On Windows resolve() reads os.getcwd(); help must not traceback with a dead cwd.
    try:
        _display_path = Path(__file__).resolve()
    except OSError:
        _display_path = Path(__file__)
    CONSOLE.print(f"  [yellow]Module:[/yellow]      [dim]{_display_path}[/dim]")
    CONSOLE.print("  [yellow]Standards:[/yellow]   [dim]See docs/display_api.md[/dim]")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    CONSOLE.print("[bold]TIP:[/bold] Run [green]drone @cli display demo[/green] to see all functions in action!")
    CONSOLE.print()
    CONSOLE.print("─" * 70)
    CONSOLE.print()

    # drone discovers commands from this line; keep its shape.
    CONSOLE.print("[dim]Commands: display, show, demo, --help[/dim]")
    CONSOLE.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle module commands"""
    if command not in ("display", "show", "demo"):
        return False
    # command holds our own name, so position 0 comes from args.
    if wants_help(None, args):
        print_help()
        return True
    if command == "demo":
        run_demo()
        return True
    if not args:
        print_introspection()
        return True
    if args[0] == "demo":
        run_demo()
        return True
    # Return True so resolve_exit reports 2 (our verb, bad token), not 1.
    error(f"Unknown display subcommand: {args[0]}", suggestion="Run 'drone @cli display --help' for usage")
    return True


def run_demo():
    """Run display function demonstrations"""
    CONSOLE.print()
    header("CLI Display Module - Demo")

    CONSOLE.print("[bold]Display functions with Rich formatting:[/bold]")
    CONSOLE.print()

    success("Operation completed successfully", items=5, time="2.3s")
    CONSOLE.print()

    warning("Template version mismatch", details="Expected v2.1, found v2.0")
    CONSOLE.print()

    # The demo error is an exhibit: clear the flag it trips unless already failed.
    failed_before = command_failed()
    error("Cannot create virtual environment", suggestion="sudo apt install python3-venv")
    if not failed_before:
        reset_command_state()
    CONSOLE.print()

    section("Summary")
    CONSOLE.print("  ✅ 3 operations succeeded")
    CONSOLE.print("  ⚠️  1 warning")
    CONSOLE.print("  ❌ 1 error")
    CONSOLE.print()

    CONSOLE.print("[bold green]✨ Rich library integration complete![/bold green]")
    CONSOLE.print("[dim]All display functions now use Rich for beautiful terminal output[/dim]")

    json_handler.log_operation("display_demo")

    CONSOLE.print()


def header(title: str, details: Optional[Dict[str, Any]] = None) -> None:
    """Display bordered section header using Rich Panel"""
    CONSOLE.print(Panel(f"[bold cyan]{title}[/bold cyan]", expand=False))
    if details:
        CONSOLE.print()
        for key, value in details.items():
            CONSOLE.print(f"  [dim]{key}:[/dim] {value}")
    CONSOLE.print()


def success(message: str, **kwargs) -> None:
    """Display success message with Rich styling"""
    CONSOLE.print(f"✅ [green]{message}[/green]")
    for key, value in kwargs.items():
        CONSOLE.print(f"   [dim]{key}: {value}[/dim]")


def error(message: str, suggestion: str | None = None) -> None:
    """Display error message with Rich styling"""
    mark_command_failed()
    msg = Text("❌ ")
    msg.append(message, style="red bold")
    err_console.print(msg)
    if suggestion:
        hint = Text("   → Try: ")
        hint.append(suggestion, style="yellow")
        err_console.print(hint)


def warning(message: str, details: str | None = None) -> None:
    """Display warning message with Rich styling"""
    msg = Text("⚠️  ")
    msg.append(message, style="yellow")
    err_console.print(msg)
    if details:
        detail_text = Text("   ")
        detail_text.append(details, style="dim")
        err_console.print(detail_text)


def fatal(message: str, suggestion: str | None = None) -> None:
    """Display error message with Rich styling and exit with code 1"""
    error(message, suggestion)
    sys.exit(1)


def section(title: str) -> None:
    """Display section separator with Rich styling"""
    CONSOLE.print()
    CONSOLE.print(f"[bold]{title}[/bold]")
    CONSOLE.print("─" * 50)


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
    "escape",
    "mark_command_failed",
    "command_failed",
    "reset_command_state",
    "resolve_exit",
]
