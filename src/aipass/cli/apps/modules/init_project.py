# =================== AIPass ====================
# Name: init_project.py
# Description: Init Project Module — orchestration layer for aipass init
# Version: 1.0.0
# Created: 2026-03-14
# Modified: 2026-03-14
# =============================================

"""
Init Project Module - PUBLIC API

Thin orchestration module for the `aipass init` command.
Routes to the init bootstrap handler for business logic.

Usage:
    drone @cli aipass init [target_dir] [project_name]
"""

import os
import sys
from pathlib import Path
from typing import List

from aipass.cli.apps.handlers.init.bootstrap import init_project
from aipass.cli.apps.modules.display import console, success, error, header


# =============================================================================
# MODULE PATTERN FUNCTIONS (SEED compliant)
# =============================================================================

def print_introspection():
    """Display module info and connected handlers."""
    console.print()
    console.print("[bold cyan]Init Project Module[/bold cyan]")
    console.print()
    console.print("[dim]Bootstrap an AIPass project in any directory[/dim]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/init/[/cyan]")
    console.print("    [dim]- bootstrap.py[/dim]")
    console.print()

    console.print("[dim]Run 'drone @cli aipass init --help' for usage[/dim]")
    console.print()


def print_help():
    """Display help for the init command."""
    console.print()
    header("aipass init - Project Bootstrap")
    console.print("[dim]Initialize an AIPass project in any directory[/dim]")
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @cli aipass init[/dim]                    Initialize in current directory")
    console.print("  [dim]drone @cli aipass init /path/to/dir[/dim]       Initialize in target directory")
    console.print("  [dim]drone @cli aipass init /path/to/dir MyProj[/dim] Initialize with custom name")
    console.print()

    console.print("[bold cyan]WHAT IT CREATES:[/bold cyan]")
    console.print()
    console.print("  [green]1.[/green] {NAME}_REGISTRY.json      Project registry with UUID")
    console.print("  [green]2.[/green] .trinity/passport.json     Project identity")
    console.print("  [green]3.[/green] .trinity/local.json        Local context (empty)")
    console.print("  [green]4.[/green] .trinity/observations.json Observations (empty)")
    console.print("  [green]5.[/green] .aipass/aipass_local_prompt.md  Local prompt")
    console.print("  [green]6.[/green] AIPASS.md                  Project prompt")
    console.print()

    console.print("[dim]Commands: init, init --help[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle 'init' command.

    Args:
        command: The subcommand string (e.g. "init")
        args: Remaining positional arguments after the subcommand

    Returns:
        True if the command was handled, False otherwise
    """
    if command != "init":
        return False

    # Handle help flag
    if args and args[0] in ("--help", "-h", "help"):
        print_help()
        return True

    # Parse positional args: [target_dir] [project_name]
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", os.getcwd())
    target = Path(args[0]) if args else Path(caller_cwd)
    project_name = args[1] if len(args) > 1 else None

    try:
        result = init_project(target, project_name)
    except ValueError as exc:
        error(str(exc), suggestion="Pass a project name explicitly")
        sys.exit(1)
    except FileExistsError as exc:
        error(str(exc), suggestion="Remove the existing file to re-initialize")
        sys.exit(1)
    except OSError as exc:
        error(f"Filesystem error: {exc}")
        sys.exit(1)

    # Display results
    header("Project Initialized")
    console.print(f"  [bold]{result['project_name']}[/bold]")
    console.print()
    success(
        f"Created {len(result['created_files'])} files",
        registry=f"{result['registry_file']} (id: {result['registry_id'][:8]}...)",
        target=result["target"],
    )
    console.print()
    console.print("[dim]Files created:[/dim]")
    for f in result["created_files"]:
        console.print(f"  [dim]{f}[/dim]")
    console.print()

    return True


# =============================================================================
# MODULE EXPORTS
# =============================================================================

__all__ = [
    "handle_command",
]


# =============================================================================
# ENTRY POINT (SEED pattern)
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
            console.print("[dim]Run 'python3 init_project.py --help' for usage[/dim]")
            sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)
