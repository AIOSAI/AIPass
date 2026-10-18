# =================== AIPass ====================
# Name: templates.py
# Description: CLI Templates Module — reusable operation output patterns
# Version: 0.3.2
# Created: 2025-11-12
# Modified: 2026-10-17
# =============================================

"""
CLI Templates Module - PUBLIC API
"""

import sys
from typing import List

from aipass.cli.apps.modules.display import console as CONSOLE, error
from aipass.cli.apps.handlers.json import json_handler
from aipass.cli.apps.handlers.cli.help_flags import wants_help
# No prax logger: circular import (prax depends on cli).


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
    CONSOLE.print("  [green]# Help for this module[/green]")
    CONSOLE.print("  drone @cli templates --help")
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
    CONSOLE.print("  [dim]See docs/display_api.md[/dim]")
    CONSOLE.print()

    CONSOLE.print("[bold]Commands: templates, demo, --help[/bold]")
    CONSOLE.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'templates' and 'demo' commands"""
    if command not in ("templates", "demo"):
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
    error(f"Unknown templates subcommand: {args[0]}", suggestion="Run 'drone @cli templates --help' for usage")
    return True


def run_demo():
    """Run template function demonstrations"""
    from aipass.cli.apps.modules.display import header

    CONSOLE.print()
    header("CLI Templates Module - Demo")

    CONSOLE.print("[bold]Operation templates with Rich formatting:[/bold]")
    CONSOLE.print()

    operation_start("Creating new branch", target="/path/to/my_branch", type="module")

    CONSOLE.print("✅ [green]Directory created[/green]")
    CONSOLE.print("   [dim]/path/to/my_branch[/dim]")
    CONSOLE.print()

    CONSOLE.print("✅ [green]Files copied[/green]")
    CONSOLE.print("   [dim]12 files from template[/dim]")
    CONSOLE.print()

    operation_complete(created=12, skipped=0, time="1.2s")

    CONSOLE.print("[bold green]✨ Rich library integration complete![/bold green]")
    CONSOLE.print("[dim]Templates provide consistent operation patterns across all branches[/dim]")

    json_handler.log_operation("templates_demo")

    CONSOLE.print()


def operation_start(operation: str, **details) -> None:
    """Display standard operation start template with Rich styling"""
    CONSOLE.print()
    CONSOLE.print(f"⚙️  [blue]{operation}...[/blue]")
    if details:
        for key, value in details.items():
            CONSOLE.print(f"   [dim]{key}: {value}[/dim]")
    CONSOLE.print()


def operation_complete(**summary) -> None:
    """Display standard operation completion template with Rich styling"""
    CONSOLE.print()
    CONSOLE.print("─" * 50)
    CONSOLE.print("[bold]Summary:[/bold]")

    for key, value in summary.items():
        CONSOLE.print(f"  {key}: {value}")

    if summary.get("time"):
        CONSOLE.print(f"  [dim]Completed in {summary['time']}[/dim]")
    CONSOLE.print()


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    command = sys.argv[1]
    args = sys.argv[2:] if len(sys.argv) > 2 else []

    if handle_command(command, args):
        sys.exit(0)
    else:
        CONSOLE.print(f"[red]Unknown command: {command}[/red]")
        CONSOLE.print("[dim]Run 'drone @cli templates --help' for usage[/dim]")
        sys.exit(1)
