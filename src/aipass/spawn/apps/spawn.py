# =================== AIPass ====================
# Name: spawn.py
# Description: Entry point CLI for drone @spawn
# Version: 1.0.1
# Created: 2026-03-05
# Modified: 2026-08-11
# =============================================

"""
SPAWN Branch - Agent Creation System

Creates new AIPass agents from templates.
Provides CLI interface to the spawn_agent() workflow.
"""

import os
import sys
import argparse

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.cli.apps.modules import console, header, error, warning


def print_help():
    """Display Rich-formatted help."""
    console.print()
    header("SPAWN - Branch Lifecycle Manager")
    console.print()
    console.print("[dim]Create, update, and manage AIPass branches with class-scoped templates[/dim]")
    console.print()
    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [dim]drone @spawn create \\[class] <target_path> \\[options][/dim]")
    console.print("  [dim]drone @spawn update <@branch | class --all> [--apply][/dim]")
    console.print(
        "  [dim]drone @spawn repair <project_path> [--clean-pollution | --relocate @branch <path>] [--apply][/dim]"
    )
    console.print("  [dim]drone @spawn --help[/dim]")
    console.print()
    console.print("[bold cyan]COMMANDS:[/bold cyan]")
    console.print()
    console.print("  [green]create[/green] \\[class] <path>         Create a new branch from template")
    console.print(
        "  [green]update[/green] <@branch>              Update single branch from templates (preview-only by default)"
    )
    console.print("  [green]update[/green] <@branch> --apply      Update single branch (execute changes)")
    console.print("  [green]update[/green] <class> --all --apply  Update all branches of a class")
    console.print("  [green]delete[/green] <@branch>              Archive and deregister branch")
    console.print("  [green]sync-registry[/green]                 Repair registry against filesystem")
    console.print("  [green]sync-templates[/green]                Pull managed files from source")
    console.print("  [green]regenerate-registry[/green]           Regenerate template registry hashes")
    console.print(
        "  [green]repair[/green] <project_path>           Scan project structure — paths/registry/pollution (read-only)"
    )
    console.print(
        "  [green]repair[/green] <path> --clean-pollution  Archive+remove duplicate dirs (preview; add --apply)"
    )
    console.print(
        "  [green]repair[/green] --relocate @branch <path> Move branch + update registry (preview; add --apply)"
    )
    console.print()
    console.print("[bold cyan]CITIZEN CLASSES:[/bold cyan]")
    console.print()
    console.print(
        "  [green]aipass_framework[/green]  Full 3-layer scaffold (apps/, modules/, handlers/) [dim][default][/dim]"
    )
    console.print()
    console.print("[bold cyan]OPTIONS:[/bold cyan]")
    console.print()
    warning("--role", details="Agent role description")
    warning("--traits", details="Agent personality traits")
    warning("--purpose", details="Agent purpose (brief)")
    warning("--template", details="Template class name (aipass_framework) or custom directory path")
    warning("--registry", details="Path to AIPASS_REGISTRY.json")
    warning("--apply", details="Execute changes (update/repair are preview-only by default)")
    warning("--dry-run", details="Preview changes without modifying files (default for update/repair)")
    warning("--trace", details="Enable verbose logging")
    console.print()
    console.print("[yellow]Examples:[/yellow]")
    console.print()
    console.print("  [dim]# Create a new branch with role and purpose[/dim]")
    console.print('  [green]drone @spawn create /path/to/new_agent --role "Analyst" --purpose "Reports"[/green]')
    console.print()
    console.print("  [dim]# Preview an update before applying[/dim]")
    console.print("  [green]drone @spawn update @branch_name[/green]")
    console.print()
    console.print("  [dim]# Sync registry against filesystem[/dim]")
    console.print("  [green]drone @spawn sync-registry --fix[/green]")
    console.print()


def handle_create(args):
    """Handle the create command with optional citizen class."""
    from aipass.spawn.apps.modules.core import _spawn_agent as spawn_agent
    from aipass.spawn.apps.modules.core import validate_class, get_default_class

    if not args:
        error("target path required", suggestion="drone @spawn create [class] <target_path> [--role ...]")
        return 1

    # Intercept --help before argparse (argparse has add_help=False)
    if "--help" in args or "-h" in args:
        print_help()
        return 0

    # Check if first arg is a citizen class
    citizen_class = get_default_class()
    remaining_args = args
    if validate_class(args[0]):
        citizen_class = args[0]
        remaining_args = args[1:]
        if not remaining_args:
            error("target path required after class name")
            return 1

    dry_run = "--dry-run" in remaining_args
    if dry_run:
        remaining_args = [a for a in remaining_args if a != "--dry-run"]

    parser = argparse.ArgumentParser(prog="spawn create", add_help=False)
    parser.add_argument("target_path")
    parser.add_argument("--role", default="")
    parser.add_argument("--traits", default="")
    parser.add_argument("--purpose", default="")
    parser.add_argument("--template", default=None)
    parser.add_argument("--registry", default=None)

    parsed = parser.parse_args(remaining_args)

    # --template can be a class name (e.g. "aipass_framework") or a raw path
    template_dir = parsed.template
    if parsed.template and validate_class(parsed.template):
        citizen_class = parsed.template
        template_dir = None

    if dry_run:
        return _dry_run_create(parsed.target_path, citizen_class, parsed)

    result = spawn_agent(
        target_path=parsed.target_path,
        role=parsed.role,
        traits=parsed.traits,
        purpose=parsed.purpose,
        template_dir=template_dir,
        registry_path=parsed.registry,
        citizen_class=citizen_class,
    )

    if result["success"]:
        console.print()
        console.print(f"[green]Agent created: {result['branch_name']}[/green]")
        console.print(f"  Class: {citizen_class}")
        console.print(f"  Path: {result['path']}")
        console.print(f"  Files: {result['files_copied']}")
        console.print(f"  Registry: {'updated' if result['registry_updated'] else 'not updated'}")
        if result["validation_issues"]:
            warning(f"{len(result['validation_issues'])} unreplaced placeholders")
        console.print()
        return 0
    else:
        error(result["error"])
        return 1


def _dry_run_create(target_path, citizen_class, parsed):
    """Preview what create would do without making changes."""
    from pathlib import Path
    from aipass.spawn.apps.modules.core import _get_template_dir, get_branch_name, normalize_branch_name

    target = Path(target_path).resolve()
    template = _get_template_dir(citizen_class)
    branch_name = get_branch_name(target)
    branch_upper = normalize_branch_name(branch_name, "upper")

    console.print()
    header("DRY RUN — Create Preview")
    console.print()
    console.print(f"  [bold]Branch:[/bold]  {branch_upper}")
    console.print(f"  [bold]Class:[/bold]   {citizen_class}")
    console.print(f"  [bold]Path:[/bold]    {target}")
    console.print(f"  [bold]Template:[/bold] {template}")
    if parsed.role:
        console.print(f"  [bold]Role:[/bold]    {parsed.role}")
    if parsed.purpose:
        console.print(f"  [bold]Purpose:[/bold] {parsed.purpose}")

    if target.exists():
        error(f"Target already exists: {target}")
        return 1

    if not template.exists():
        error(f"Template not found: {template}")
        return 1

    # Count template files
    file_count = sum(1 for f in template.rglob("*") if f.is_file() and "__pycache__" not in str(f))
    dir_count = sum(1 for d in template.rglob("*") if d.is_dir() and "__pycache__" not in str(d))

    console.print()
    console.print("  [bold cyan]Would create:[/bold cyan]")
    console.print(f"    Files:       ~{file_count}")
    console.print(f"    Directories: ~{dir_count}")
    console.print("    Registry:    add to AIPASS_REGISTRY.json")
    console.print()
    console.print("  [dim]No files were created. Remove --dry-run to execute.[/dim]")
    console.print()
    return 0


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]spawn Entry Point[/bold cyan]")
    console.print("Branch lifecycle manager — create, update, delete, and sync AIPass branches")
    console.print()
    console.print("[yellow]Connected Modules:[/yellow]")
    console.print("  [cyan]modules/[/cyan]")
    console.print("    [dim]- core.py (handle_command, _spawn_agent — agent creation orchestrator)[/dim]")
    console.print("    [dim]- update.py (handle_update — single/all branch updates)[/dim]")
    console.print("    [dim]- delete.py (handle_delete — archive and deregister branch)[/dim]")
    console.print("    [dim]- sync_registry.py (handle_sync_registry — registry repair)[/dim]")
    console.print("    [dim]- sync_templates.py (handle_sync_templates — template synchronization)[/dim]")
    console.print("    [dim]- regenerate_registry.py (handle_regenerate_registry — regenerate template registry)[/dim]")
    console.print("    [dim]- repair.py (handle_repair — project structure repair)[/dim]")
    console.print()
    console.print("[dim]Run 'drone @spawn --help' for usage information[/dim]")
    console.print()


def main():
    """Main entry point."""
    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        return 0

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return 0

    if args[0] in ["--version", "-V"]:
        console.print("SPAWN v1.0.0")
        return 0

    command = args[0]
    remaining = args[1:] if len(args) > 1 else []

    if remaining and remaining[0] in ["--help", "-h"]:
        remaining = ["--help"]

    if command == "create":
        return handle_create(remaining)

    if command == "update":
        from aipass.spawn.apps.modules.update import handle_update

        return handle_update(remaining)

    if command == "delete":
        from aipass.spawn.apps.modules.delete import handle_delete

        return handle_delete(remaining)

    if command == "sync-registry":
        from aipass.spawn.apps.modules.sync_registry import handle_sync_registry

        return handle_sync_registry(remaining)

    if command == "sync-templates":
        from aipass.spawn.apps.modules.sync_templates import handle_sync_templates

        return handle_sync_templates(remaining)

    if command == "regenerate-registry":
        from aipass.spawn.apps.modules.regenerate_registry import handle_regenerate_registry

        return handle_regenerate_registry(remaining)

    if command == "repair":
        from aipass.spawn.apps.modules.repair import handle_repair

        return handle_repair(remaining)

    error(f"Unknown command: {command}", suggestion="Run 'drone @spawn --help' for available commands")
    return 1


if __name__ == "__main__":
    if sys.platform == "win32":
        os.environ.setdefault("PYTHONUTF8", "1")
        for _stream in (sys.stdout, sys.stderr):
            _reconfigure = getattr(_stream, "reconfigure", None)
            if _reconfigure is not None:
                _reconfigure(encoding="utf-8", errors="replace")

    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.warning("SPAWN interrupted by user (KeyboardInterrupt)")
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"SPAWN entry point error: {e}", exc_info=True)
        console.print(f"\nError: {e}")
        sys.exit(1)
