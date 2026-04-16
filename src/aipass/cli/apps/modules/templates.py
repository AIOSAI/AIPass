# =================== AIPass ====================
# Name: templates.py
# Description: CLI Templates Module — reusable operation output patterns
# Version: 0.3.0
# Created: 2025-11-12
# Modified: 2025-11-15
# =============================================

"""
CLI Templates Module - PUBLIC API

Pre-built output templates for common operations:
- operation_start() - Standard operation header
- operation_complete() - Standard completion summary

Uses Rich library for beautiful terminal output.
"""

import sys
from typing import List

# Import console from CLI display module (using our own service!)
from aipass.cli.apps.modules.display import console as CONSOLE
from aipass.cli.apps.handlers.json import json_handler
# NOTE: Cannot import prax here — circular import (prax depends on cli)
# from aipass.prax import logger


# ============================================================================
# MODULE PATTERN FUNCTIONS (SEEDGO compliant)
# ============================================================================


def print_introspection():
    """Display module info and connected handlers"""
    CONSOLE.print()
    CONSOLE.print("[bold cyan]CLI Templates Module[/bold cyan]")
    CONSOLE.print()

    CONSOLE.print("[yellow]Functions:[/yellow]")
    CONSOLE.print()
    CONSOLE.print("  [cyan]operation_start()[/cyan]      Standard operation header with details")
    CONSOLE.print("  [cyan]operation_complete()[/cyan]   Completion summary with optional timing")
    CONSOLE.print()

    CONSOLE.print("[dim]Run 'drone @cli templates --help' for usage[/dim]")
    CONSOLE.print()


def print_help():
    """Print Rich-formatted help output"""
    # Import header from CLI services
    from aipass.cli.apps.modules.display import header

    CONSOLE.print()
    header("CLI Templates Module - Reusable Operation Output Patterns")

    CONSOLE.print("[bold cyan]What This Module Provides:[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("  [yellow]operation_start(operation, **details)[/yellow]")
    CONSOLE.print("    Standard operation header with Rich styling")
    CONSOLE.print("    Example: operation_start('Creating branch', target='/path', type='module')")
    CONSOLE.print()
    CONSOLE.print("  [yellow]operation_complete(**summary)[/yellow]")
    CONSOLE.print("    Standard completion summary with Rich styling")
    CONSOLE.print("    Example: operation_complete(created=5, skipped=2, time='3.2s')")
    CONSOLE.print()

    CONSOLE.print("[bold cyan]Usage Examples:[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("  [green]# Show module info[/green]")
    CONSOLE.print("  drone @cli templates")
    CONSOLE.print()
    CONSOLE.print("  [green]# Run demo[/green]")
    CONSOLE.print("  drone @cli templates demo")
    CONSOLE.print()
    CONSOLE.print("  [green]# Via drone[/green]")
    CONSOLE.print("  drone cli templates")
    CONSOLE.print("  drone cli ops demo")
    CONSOLE.print()

    CONSOLE.print("[bold cyan]Integration Example:[/bold cyan]")
    CONSOLE.print()
    CONSOLE.print("  [dim]from aipass.cli.apps.modules.templates import operation_start, operation_complete[/dim]")
    CONSOLE.print()
    CONSOLE.print("  [dim]# Start operation[/dim]")
    CONSOLE.print("  [dim]operation_start('Creating files', target='/path/to/my_branch')[/dim]")
    CONSOLE.print()
    CONSOLE.print("  [dim]# ... do work ...[/dim]")
    CONSOLE.print()
    CONSOLE.print("  [dim]# Complete operation[/dim]")
    CONSOLE.print("  [dim]operation_complete(created=12, skipped=0, time='1.2s')[/dim]")
    CONSOLE.print()

    CONSOLE.print("[bold cyan]Reference:[/bold cyan]")
    CONSOLE.print("  [dim]See CODE_STANDARDS/cli.md[/dim]")
    CONSOLE.print()

    CONSOLE.print("[bold]Commands: templates, demo, --help[/bold]")
    CONSOLE.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'templates' and 'demo' commands"""
    if command == "demo":
        run_demo()
        return True
    if command != "templates":
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
    """Run template function demonstrations"""
    from aipass.cli.apps.modules.display import header

    CONSOLE.print()
    header("CLI Templates Module - Demo")

    CONSOLE.print("[bold]Operation templates with Rich formatting:[/bold]")
    CONSOLE.print()

    # Demo operation start
    operation_start("Creating new branch", target="/path/to/my_branch", type="module")

    # Simulate some work
    CONSOLE.print("✅ [green]Directory created[/green]")
    CONSOLE.print("   [dim]/path/to/my_branch[/dim]")
    CONSOLE.print()

    CONSOLE.print("✅ [green]Files copied[/green]")
    CONSOLE.print("   [dim]12 files from template[/dim]")
    CONSOLE.print()

    # Demo operation complete
    operation_complete(created=12, skipped=0, time="1.2s")

    CONSOLE.print("[bold green]✨ Rich library integration complete![/bold green]")
    CONSOLE.print("[dim]Templates provide consistent operation patterns across all branches[/dim]")

    json_handler.log_operation("templates_demo")

    CONSOLE.print()


# ============================================================================
# PUBLIC API FUNCTIONS (Keep existing - don't break compatibility)
# ============================================================================


def operation_start(operation: str, **details) -> None:
    """
    Display standard operation start template with Rich styling

    Args:
        operation: Operation name
        **details: Operation details to display

    Example:
        operation_start('Create Branch', target='/path', name='mybranch')
    """
    CONSOLE.print()
    CONSOLE.print(f"⚙️  [blue]{operation}...[/blue]")
    if details:
        for key, value in details.items():
            CONSOLE.print(f"   [dim]{key}: {value}[/dim]")
    CONSOLE.print()


def operation_complete(**summary) -> None:
    """
    Display standard operation completion template with Rich styling

    Args:
        **summary: Summary statistics

    Example:
        operation_complete(created=5, skipped=2, time='3.2s')
    """
    CONSOLE.print()
    CONSOLE.print("─" * 50)
    CONSOLE.print("[bold]Summary:[/bold]")

    for key, value in summary.items():
        CONSOLE.print(f"  {key}: {value}")

    if summary.get("time"):
        CONSOLE.print(f"  [dim]Completed in {summary['time']}[/dim]")
    CONSOLE.print()


# ============================================================================
# ENTRY POINT (SEEDGO pattern)
# ============================================================================

if __name__ == "__main__":
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
        CONSOLE.print("[dim]Run 'drone @cli templates --help' for usage[/dim]")
        sys.exit(1)
