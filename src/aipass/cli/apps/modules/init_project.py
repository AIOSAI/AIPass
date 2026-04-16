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
import subprocess
import sys
from pathlib import Path
from typing import List

from aipass.cli.apps.handlers.init.bootstrap import init_project, update_project
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
    table.add_row(
        "init agent",
        "Create an agent in current project",
        "drone @cli aipass init agent my_agent",
    )
    table.add_row(
        "init update",
        "Refresh managed scaffold files",
        "drone @cli aipass init update",
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
    console.print(
        "  [green]drone @cli aipass init agent <name>[/green]     [dim]Create an agent in current project[/dim]"
    )
    console.print("  [green]drone @cli aipass init update[/green]           [dim]Refresh managed scaffold files[/dim]")
    console.print("  [green]drone @cli aipass --help[/green]                [dim]This help message[/dim]")
    console.print()
    console.print("─" * 70)
    console.print()

    # What init creates
    console.print("[bold cyan]WHAT INIT CREATES:[/bold cyan]")
    console.print()

    files_text = """[bold]Project scaffold (12 items):[/bold]

  [green]1.[/green]  [yellow]{NAME}_REGISTRY.json[/yellow]            Project registry with UUID
  [green]2.[/green]  [yellow].aipass/aipass_global_prompt.md[/yellow]  Global prompt (injected every turn)
  [green]3.[/green]  [yellow]CLAUDE.md[/yellow]                       Project prompt (Claude Code)
  [green]4.[/green]  [yellow]AGENTS.md[/yellow]                       Codex instructions
  [green]5.[/green]  [yellow]GEMINI.md[/yellow]                       Gemini instructions
  [green]6.[/green]  [yellow]README.md[/yellow]                       Getting started guide
  [green]7.[/green]  [yellow]STATUS.local.md[/yellow]                 Project status
  [green]8.[/green]  [yellow].gitignore[/yellow]                      Standard AIPass ignores
  [green]9.[/green]  [yellow].claude/settings.json[/yellow]           Claude Code hooks + AIPASS_HOME
  [green]10.[/green] [yellow]hooks/[/yellow]                          User hooks directory
  [green]11.[/green] [yellow]src/[/yellow]                            Agent directories live here
  [green]12.[/green] [yellow].ai_mail.local/inbox.json[/yellow]       Empty project mailbox"""

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
    # Direct subcommand: 'aipass init /path' on PATH → command="init"
    if command == "init":
        return _handle_init(args)

    # Direct subcommand shortcut: command="update" → treated as 'init update'
    if command == "update":
        return _handle_init(["update"] + args)

    # Prefixed command: 'drone @cli aipass init' → command="aipass"
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

    # Route 'init update' to update handler
    if args and args[0] == "update":
        return _handle_init_update(args[1:])

    # Route 'init agent <name>' to spawn
    if args and args[0] == "agent":
        return _handle_init_agent(args[1:])

    # Parse positional args: [target_dir] [project_name]
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", os.getcwd())
    if args:
        target = Path(args[0])
        if not target.is_absolute():
            target = Path(caller_cwd) / target
    else:
        target = Path(caller_cwd)
    project_name = args[1] if len(args) > 1 else None

    try:
        result = init_project(target, project_name)
    except ValueError as exc:
        logger.warning("Init validation error: %s", exc)
        error(str(exc), suggestion="Pass a project name explicitly")
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

    if result.get("aipass_home"):
        console.print()
        console.print(f"[bold cyan]AIPASS_HOME:[/bold cyan] [yellow]{result['aipass_home']}[/yellow]")
        console.print("[dim]For terminal usage, add to your shell profile:[/dim]")
        console.print(f"  [green]export AIPASS_HOME={result['aipass_home']}[/green]")

    json_handler.log_operation(
        "aipass_init",
        {
            "project_name": result["project_name"],
            "target": result["target"],
            "files_created": len(result["created_files"]),
        },
    )

    # Next steps
    console.print()
    console.print("[bold cyan]Next steps:[/bold cyan]")
    console.print("  [green]1.[/green] Create your first agent:  [yellow]aipass init agent <name>[/yellow]")
    console.print("  [green]2.[/green] Start a session:          [dim]cd src/<name>/ && claude[/dim]")
    console.print("  [green]3.[/green] Read the docs:            [dim]cat README.md[/dim]")
    console.print()

    return True


def _handle_init_agent(args: List[str]) -> bool:
    """Handle 'aipass init agent <name>' — routes to drone @spawn create."""
    if not args or args[0] in ("--help", "-h", "help"):
        console.print()
        header("aipass init agent — Create an Agent")
        console.print("[dim]Creates a new agent inside the current project[/dim]")
        console.print()
        console.print("[bold cyan]Usage:[/bold cyan]")
        console.print("  [green]aipass init agent <name>[/green]")
        console.print("  [green]drone @cli aipass init agent <name>[/green]")
        console.print()
        console.print("[bold cyan]What it does:[/bold cyan]")
        console.print("  Routes to [yellow]drone @spawn create src/<name>[/yellow]")
        console.print("  Creates full agent scaffold in src/<name>/ (apps/, .trinity/, .ai_mail.local/)")
        console.print("  Registers agent in the project registry")
        console.print()
        console.print("[dim]Commands: init agent, init agent --help[/dim]")
        console.print()
        return True

    agent_name = args[0]
    agent_path = f"src/{agent_name}"
    extra_flags = args[1:]
    logger.info("Routing 'init agent %s' to drone @spawn create %s", agent_name, agent_path)

    try:
        result = subprocess.run(
            ["drone", "@spawn", "create", agent_path] + extra_flags,
            check=False,
        )
        if result.returncode != 0:
            error(
                f"Agent creation failed (exit {result.returncode})",
                suggestion="Check drone @spawn create --help",
            )
        return True
    except FileNotFoundError:
        logger.warning("drone command not found on PATH")
        error(
            "drone command not found",
            suggestion="Ensure AIPass is installed and drone is in PATH",
        )
        return True


def _handle_init_update(args: List[str]) -> bool:
    """Handle 'aipass init update' — refresh managed scaffold files."""
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    if args and args[0] in ("--help", "-h", "help"):
        console.print()
        header("aipass init update — Refresh Scaffold Files")
        console.print("[dim]Updates managed prompt and config files with the latest templates[/dim]")
        console.print()
        console.print("[bold cyan]Usage:[/bold cyan]")
        console.print("  [green]drone @cli aipass init update[/green]             [dim]Update current directory[/dim]")
        console.print("  [green]drone @cli aipass init update /path/to/dir[/green]  [dim]Update target directory[/dim]")
        console.print()
        console.print("[bold cyan]What gets updated:[/bold cyan]")
        console.print("  .aipass/aipass_global_prompt.md, .claude/settings.json")
        console.print("  CLAUDE.md, AGENTS.md, GEMINI.md")
        console.print()
        console.print("[bold cyan]What is never touched:[/bold cyan]")
        console.print("  *_REGISTRY.json, README.md, STATUS.local.md, .gitignore, hooks/, src/")
        console.print()
        console.print("[dim]Commands: init update, init update --help[/dim]")
        console.print()
        return True

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", os.getcwd())
    target = Path(args[0]) if args else Path(caller_cwd)
    if not target.is_absolute():
        target = Path(caller_cwd) / target

    try:
        result = update_project(target)
    except ValueError as exc:
        logger.warning("Init update validation error: %s", exc)
        error(str(exc), suggestion="Run 'aipass init' first to create the project")
        sys.exit(1)
    except OSError as exc:
        logger.error("Init update filesystem error: %s", exc)
        error(f"Filesystem error: {exc}")
        sys.exit(1)

    # Display results
    console.print()
    header("Project Updated")

    already_current = result.get("already_current", [])
    summary = (
        f"[bold]{result['project_name']}[/bold]\n"
        f"\n"
        f"  [yellow]Target:[/yellow]          [dim]{result['target']}[/dim]\n"
        f"  [yellow]Updated:[/yellow]         {len(result['updated_files'])} files\n"
        f"  [yellow]Already current:[/yellow] {len(already_current)} files\n"
        f"  [yellow]User-owned:[/yellow]      {len(result['skipped_files'])} files (skipped)"
    )
    console.print(Panel(summary, border_style="green", box=box.ROUNDED))

    # Updated files table (only show if something changed)
    if result["updated_files"]:
        updated_table = Table(show_header=True, header_style="bold cyan", border_style="dim", title="Updated")
        updated_table.add_column("#", style="green", width=3)
        updated_table.add_column("File", style="yellow")
        for i, f in enumerate(result["updated_files"], 1):
            updated_table.add_row(str(i), f)
        console.print(updated_table)

    # Already current table
    if already_current:
        current_table = Table(show_header=True, header_style="bold cyan", border_style="dim", title="Already current")
        current_table.add_column("#", style="dim", width=3)
        current_table.add_column("File", style="dim")
        for i, f in enumerate(already_current, 1):
            current_table.add_row(str(i), f)
        console.print(current_table)

    # Skipped files table
    skipped_table = Table(show_header=True, header_style="bold cyan", border_style="dim", title="User-owned (skipped)")
    skipped_table.add_column("#", style="dim", width=3)
    skipped_table.add_column("File", style="dim")
    for i, f in enumerate(result["skipped_files"], 1):
        skipped_table.add_row(str(i), f)
    console.print(skipped_table)
    console.print()

    if result["updated_files"]:
        success(f"Updated {len(result['updated_files'])} files")
    else:
        success("All files already up to date")

    json_handler.log_operation(
        "aipass_init_update",
        {
            "project_name": result["project_name"],
            "target": result["target"],
            "files_updated": len(result["updated_files"]),
            "files_already_current": len(already_current),
            "files_skipped": len(result["skipped_files"]),
        },
    )

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
    usage_table.add_row("drone @cli aipass init update", "Refresh managed scaffold files")
    usage_table.add_row("drone @cli aipass init update /path", "Refresh scaffold in target directory")
    console.print(usage_table)
    console.print()
    console.print("─" * 70)
    console.print()

    # What it creates
    console.print("[bold cyan]WHAT IT CREATES:[/bold cyan]")
    console.print()

    files_text = """[bold]Project scaffold (12 items):[/bold]

  [green]1.[/green]  [yellow]{NAME}_REGISTRY.json[/yellow]            Project registry with UUID
  [green]2.[/green]  [yellow].aipass/aipass_global_prompt.md[/yellow]  Global prompt (injected every turn)
  [green]3.[/green]  [yellow]CLAUDE.md[/yellow]                       Project prompt (Claude Code)
  [green]4.[/green]  [yellow]AGENTS.md[/yellow]                       Codex instructions
  [green]5.[/green]  [yellow]GEMINI.md[/yellow]                       Gemini instructions
  [green]6.[/green]  [yellow]README.md[/yellow]                       Getting started guide
  [green]7.[/green]  [yellow]STATUS.local.md[/yellow]                 Project status
  [green]8.[/green]  [yellow].gitignore[/yellow]                      Standard AIPass ignores
  [green]9.[/green]  [yellow].claude/settings.json[/yellow]           Claude Code hooks + AIPASS_HOME
  [green]10.[/green] [yellow]hooks/[/yellow]                          User hooks directory
  [green]11.[/green] [yellow]src/[/yellow]                            Agent directories live here
  [green]12.[/green] [yellow].ai_mail.local/inbox.json[/yellow]       Empty project mailbox"""

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
