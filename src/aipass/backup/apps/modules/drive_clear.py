# =================== AIPass ====================
# Name: drive_clear.py
# Description: Drive clear module — clears Drive file tracker (requires --force)
# Version: 1.1.1
# Created: 2026-04-17
# Modified: 2026-11-26
# =============================================

"""Drive Clear Module — clears the Drive file tracker for a project."""

import sys

from aipass.prax import logger
from aipass.cli import console, error as cli_error

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.caller import resolve_caller_path, store_delete_refusal


MODULE_NAME = "drive_clear"
PRIMARY_COMMAND = "drive_clear"


def print_introspection():
    """Display module info and connected handlers."""
    console.print(f"[bold cyan]{MODULE_NAME} Module[/bold cyan]")
    console.print("  [dim]Clears a project's local Drive tracker; remote files stay[/dim]")
    console.print(f"  Primary command: [yellow]{PRIMARY_COMMAND}[/yellow]")
    console.print("  Handlers: drive/tracker (requires --force)")
    console.print("  [dim]Run 'drone @backup drive_clear --help' for usage[/dim]")


def print_help():
    """Display help for this module."""
    print_introspection()
    console.print()
    console.print("[yellow]Usage:[/yellow] [cyan]drive_clear[/cyan] <project_root> --force")
    console.print("  [green]--force[/green]   Required to confirm tracker deletion")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print("  [cyan]drone @backup drive_clear . --force[/cyan]")


def run_drive_clear(project_root: str, force: bool = False) -> bool:
    """Clear Drive tracker. Requires force=True."""
    from aipass.backup.apps.handlers.drive.tracker import clear_all

    if not force:
        console.print("[dim]Use --force to confirm tracker deletion.[/dim]")
        return False

    success = clear_all(project_root)
    if success:
        console.print("[green]Drive tracker cleared.[/green]")
        logger.info(f"[backup] Drive tracker cleared for {project_root}")
    else:
        cli_error("Failed to clear Drive tracker.")

    trail.log_operation(
        "drive_clear_complete",
        {"project_root": project_root, "success": success},
    )
    return success


def handle_command(command: str, args: list) -> bool:
    """Handle the drive-clear-tracker command. Returns True if handled."""
    if command != PRIMARY_COMMAND:
        return False

    if not args:
        print_introspection()
        return True

    # Screen every arg: the standalone __main__ skips the router's help normalisation.
    # Bare "help" is first-position only; later args are user values.
    if args[0] == "help" or any(arg in ("--help", "-h") for arg in args):
        print_help()
        return True

    project_root = resolve_caller_path(args[0])
    force = "--force" in args
    refusal = store_delete_refusal("drive_clear --force", project_root) if force else None
    if refusal:
        cli_error(f"Drive clear refused: {refusal}")
        return True
    run_drive_clear(str(project_root), force=force)
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_introspection()
        sys.exit(0)
    handle_command(PRIMARY_COMMAND, sys.argv[1:])
