# =================== AIPass ====================
# Name: retire_project.py
# Description: Project retirement — thin CLI layer for retiring a whole project from the admin seat
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""retire-project: the admin seat retires a whole project, owner included, with one receipt row per removal."""

from aipass.prax import logger

from aipass.cli.apps.modules import console, error, warning

from aipass.spawn.apps.handlers.delete_ops import retire_project
from aipass.spawn.apps.handlers.json import json_handler

_USAGE = "drone @spawn retire-project <project_root> (--yes | --dry-run)"


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]retire_project Module[/bold cyan]")
    console.print("Project retirement — archive into AIPass, flip passports, revoke trust, remove, write receipts")
    console.print()
    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  [cyan]handlers/[/cyan]")
    console.print("    [dim]- delete_ops.py (retire_project — guards, archive, trust revoke, removal)[/dim]")
    console.print("    [dim]- deletion_receipts.py (measure, validate and write the receipt rows)[/dim]")
    console.print()


def _print_usage() -> None:
    """The verb's usage lines."""
    console.print(f"[bold cyan]Usage:[/bold cyan] {_USAGE}")
    console.print()
    console.print("  [green]project_root[/green]  Directory holding the project's *_REGISTRY.json")
    console.print("  [green]--yes[/green]         Retire it (verified admin seat only)")
    console.print("  [green]--dry-run[/green]     List what would go and its receipt rows; writes nothing")
    console.print()
    console.print("  [dim]Archive: <AIPass>/.archive/deleted_branches/<project>_<timestamp>/[/dim]")
    console.print("  [dim]Receipts: grep spawn_retire <AIPass>/.ai_central/deletions.jsonl[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command != "retire-project":
        return False
    if not args:
        print_introspection()
        return True
    if "--help" in args:
        print_introspection()
        return True
    return handle_retire_project(args) == 0


def handle_retire_project(args: list[str]) -> int:
    """Parse args and retire a project; returns exit code (0=success, 1=failure)."""
    if "--help" in args or "-h" in args:
        _print_usage()
        return 0

    targets = [a for a in args if not a.startswith("--")]
    dry_run = "--dry-run" in args
    if not targets or not (dry_run or "--yes" in args):
        warning(f"Usage: {_USAGE}")
        return 1

    result = retire_project(targets[0], dry_run=dry_run)
    if not result["success"] and not result["rows"]:
        logger.warning(f"[retire-project] refused {targets[0]}: {result['error']}")
        error(f"Retire-project REFUSED {targets[0]}: {result['error']}")
        return 1

    _print_rows(result, dry_run)
    if not result["success"]:
        error(result["error"])
        return 1
    json_handler.log_operation("retire_project", data={"project": result["project"], "dry_run": dry_run})
    return 0


def _print_rows(result: dict, dry_run: bool) -> None:
    """Print each thing that goes and where the archive lands."""
    verb = "would go" if dry_run else "retired"
    console.print()
    console.print(f"[bold]{result['project']}[/bold] {verb}:")
    for row in result["rows"]:
        m = row["measurement"]
        console.print(f"  {m['kind']:<11} {row['resolved']}  ({m['size_bytes']} bytes, {m['entry_count']} entries)")
    console.print(f"  Archive: {result['archive_path']}")
    if dry_run:
        seat = "yes" if result["admin"] else "no - --yes would be refused"
        console.print(f"  Admin seat: {seat}")
        console.print(f"  Receipt rows: {len(result['rows'])}, written only by --yes")
    console.print()
