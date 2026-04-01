# =================== AIPass ====================
# Name: init_project.py
# Description: AIPass Project Commands Module — owns the 'aipass' top-level command
# Version: 2.0.0
# Created: 2026-03-14
# Modified: 2026-03-15
# =============================================

"""
AIPass Project Commands Module

Owns the 'aipass' top-level command and routes subcommands (init, etc.).
Follows seedgo module interface: handle_command(), print_introspection(), print_help().

Run: drone @cli aipass
"""

import os
import sys
from pathlib import Path
from typing import List

from aipass.cli.apps.handlers.init.bootstrap import init_project
from aipass.cli.apps.modules.display import console, success, error, header
from aipass.cli.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger


# =============================================================================
# MODULE PATTERN FUNCTIONS (SEEDGO compliant)
# =============================================================================

def print_introspection():
    """Display aipass command info — available subcommands and connected handlers."""
    from rich.table import Table

    console.print()
    console.print("[bold cyan]aipass — Project Commands[/bold cyan]")
    console.print("[dim]Manage AIPass projects from the command line[/dim]")
    console.print()

    # Available subcommands
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Command", style="green")
    table.add_column("Description", style="white")
    table.add_column("Example", style="dim")

    table.add_row(
        "init",
        "Bootstrap a new AIPass project",
        "drone @cli aipass init /path MyProject",
    )

    console.print(table)
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/init/[/cyan]")
    console.print("    [dim]- bootstrap.py[/dim]")
    console.print()

    console.print("[yellow]Next:[/yellow]  Run a subcommand")
    console.print("  [green]drone @cli aipass init[/green]            [dim]# Bootstrap a project[/dim]")
    console.print("  [green]drone @cli aipass init --help[/green]     [dim]# Detailed init usage[/dim]")
    console.print("  [green]drone @cli aipass --help[/green]          [dim]# Full help[/dim]")
    console.print()


def print_help():
    """Display Rich-formatted help for the aipass command and all subcommands."""
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    console.print()
    header("aipass — Project Commands")
    console.print("[dim]Manage AIPass projects from the command line[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    # Subcommands
    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    console.print("  [green]drone @cli aipass[/green]                       [dim]Show available subcommands[/dim]")
    console.print("  [green]drone @cli aipass init[/green]                  [dim]Bootstrap in current directory[/dim]")
    console.print("  [green]drone @cli aipass init /path[/green]            [dim]Bootstrap in target directory[/dim]")
    console.print("  [green]drone @cli aipass init /path MyProj[/green]     [dim]Bootstrap with custom name[/dim]")
    console.print("  [green]drone @cli aipass --help[/green]                [dim]This help message[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    # What init creates
    console.print("[bold cyan]WHAT INIT CREATES:[/bold cyan]")
    console.print()

    files_text = """[bold]Project scaffold (6 files):[/bold]

  [green]1.[/green] [yellow]{NAME}_REGISTRY.json[/yellow]       Project registry with UUID
  [green]2.[/green] [yellow].trinity/passport.json[/yellow]      Project identity (with registry_id)
  [green]3.[/green] [yellow].trinity/local.json[/yellow]         Session history & learnings
  [green]4.[/green] [yellow].trinity/observations.json[/yellow]  Collaboration patterns
  [green]5.[/green] [yellow].aipass/aipass_local_prompt.md[/yellow]  Local prompt (injected every turn)
  [green]6.[/green] [yellow]AIPASS.md[/yellow]                   Project prompt (persists in context)"""

    console.print(Panel(files_text, border_style="green", padding=(1, 2), box=box.ROUNDED))
    console.print()
    console.print("─" * 70)
    console.print()

    # Arguments
    console.print("[bold cyan]ARGUMENTS (init):[/bold cyan]")
    console.print()

    args_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    args_table.add_column("Argument", style="green")
    args_table.add_column("Required", style="yellow")
    args_table.add_column("Default", style="dim")
    args_table.add_column("Description", style="white")
    args_table.add_row("target_dir", "No", "Current directory", "Directory to initialize")
    args_table.add_row("project_name", "No", "Directory name", "Name for registry (auto-uppercased)")
    console.print(args_table)
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[dim]Commands: aipass, aipass init, aipass --help[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'aipass' command with subcommand routing.

    Args:
        command: The command string (e.g. "aipass")
        args: Remaining arguments after the command
            [] -> show introspection (available subcommands)
            ["init"] -> run init
            ["init", "--help"] -> show init help
            ["--help"] -> show full help

    Returns:
        True if handled, False if not this module's command
    """
    if command != "aipass":
        return False

    # No subcommand -> show introspection
    if not args:
        print_introspection()
        return True

    # Help flag -> show full help
    if args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    subcmd = args[0]
    sub_args = args[1:]

    # Route subcommands
    if subcmd == "init":
        return _handle_init(sub_args)

    error(f"Unknown aipass subcommand: {subcmd}", suggestion="drone @cli aipass --help")
    return True


def _handle_init(args: List[str]) -> bool:
    """Handle the 'init' subcommand."""
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    # Handle help flag
    if args and args[0] in ("--help", "-h", "help"):
        _print_init_help()
        return True

    # Parse positional args: [target_dir] [project_name]
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", os.getcwd())
    target = Path(args[0]) if args else Path(caller_cwd)
    project_name = args[1] if len(args) > 1 else None

    try:
        result = init_project(target, project_name)
    except ValueError as exc:
        logger.warning("Init validation error: %s", exc)
        error(str(exc), suggestion="Pass a project name explicitly")
        sys.exit(1)
    except FileExistsError as exc:
        logger.warning("Init target already exists: %s", exc)
        error(str(exc), suggestion="Remove the existing file to re-initialize")
        sys.exit(1)
    except OSError as exc:
        logger.error("Init filesystem error: %s", exc)
        error(f"Filesystem error: {exc}")
        sys.exit(1)

    # Display results
    console.print()
    header("Project Initialized")

    # Summary panel
    summary = (
        f"[bold]{result['project_name']}[/bold]\n"
        f"\n"
        f"  [yellow]Registry:[/yellow]  {result['registry_file']}\n"
        f"  [yellow]ID:[/yellow]        [dim]{result['registry_id'][:8]}...[/dim]\n"
        f"  [yellow]Target:[/yellow]    [dim]{result['target']}[/dim]"
    )
    console.print(Panel(summary, border_style="green", box=box.ROUNDED))

    # Files table
    files_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    files_table.add_column("#", style="green", width=3)
    files_table.add_column("File", style="yellow")
    for i, f in enumerate(result["created_files"], 1):
        files_table.add_row(str(i), f)
    console.print(files_table)
    console.print()

    success(f"Created {len(result['created_files'])} files")

    json_handler.log_operation("aipass_init", {
        "project_name": result["project_name"],
        "target": result["target"],
        "files_created": len(result["created_files"]),
    })

    console.print()

    return True


def _print_init_help():
    """Display detailed help for the init subcommand."""
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    console.print()
    header("aipass init — Project Bootstrap")
    console.print("[dim]Initialize an AIPass project in any directory[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    # Usage examples
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()

    usage_table = Table(show_header=False, border_style="dim", box=box.SIMPLE, padding=(0, 2))
    usage_table.add_column("Command", style="yellow")
    usage_table.add_column("Description", style="white")
    usage_table.add_row("drone @cli aipass init", "Initialize in current directory")
    usage_table.add_row("drone @cli aipass init /path/to/dir", "Initialize in target directory")
    usage_table.add_row("drone @cli aipass init /path MyProj", "Initialize with custom project name")
    console.print(usage_table)
    console.print()
    console.print("─" * 70)
    console.print()

    # What it creates
    console.print("[bold cyan]WHAT IT CREATES:[/bold cyan]")
    console.print()

    files_text = """[bold]Project scaffold (6 files):[/bold]

  [green]1.[/green] [yellow]{NAME}_REGISTRY.json[/yellow]       Project registry with UUID
  [green]2.[/green] [yellow].trinity/passport.json[/yellow]      Project identity (with registry_id)
  [green]3.[/green] [yellow].trinity/local.json[/yellow]         Session history & learnings
  [green]4.[/green] [yellow].trinity/observations.json[/yellow]  Collaboration patterns
  [green]5.[/green] [yellow].aipass/aipass_local_prompt.md[/yellow]  Local prompt (injected every turn)
  [green]6.[/green] [yellow]AIPASS.md[/yellow]                   Project prompt (persists in context)"""

    console.print(Panel(files_text, border_style="green", padding=(1, 2), box=box.ROUNDED))
    console.print()
    console.print("─" * 70)
    console.print()

    # Arguments
    console.print("[bold cyan]ARGUMENTS:[/bold cyan]")
    console.print()

    args_table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    args_table.add_column("Argument", style="green")
    args_table.add_column("Required", style="yellow")
    args_table.add_column("Default", style="dim")
    args_table.add_column("Description", style="white")
    args_table.add_row("target_dir", "No", "Current directory", "Directory to initialize")
    args_table.add_row("project_name", "No", "Directory name", "Name for registry (auto-uppercased)")
    console.print(args_table)
    console.print()
    console.print("─" * 70)
    console.print()

    console.print("[dim]Commands: init, init --help[/dim]")
    console.print()


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "handle_command",
]


# =============================================================================
# ENTRY POINT (SEEDGO pattern)
# =============================================================================

if __name__ == "__main__":
    try:
        if len(sys.argv) == 1:
            print_introspection()
            sys.exit(0)

        if sys.argv[1] in ("--help", "-h", "help"):
            print_help()
            sys.exit(0)

        command = sys.argv[1]
        cmd_args = sys.argv[2:] if len(sys.argv) > 2 else []

        if handle_command(command, cmd_args):
            sys.exit(0)
        else:
            console.print(f"[red]Unknown command: {command}[/red]")
            console.print("[dim]Run 'drone @cli aipass --help' for usage[/dim]")
            sys.exit(1)
    except Exception as e:
        logger.error("CLI init_project error: %s", e)
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
