# =================== AIPass ====================
# Name: trust.py
# Description: Trust management — aipass trust / aipass revoke commands
# Version: 1.0.0
# Created: 2026-07-15
# Modified: 2026-07-15
# =============================================

"""
aipass trust / revoke — manage the trusted-project registry (DPLAN-0244)

Enrollment controls which projects have their .aipass/hooks.json loaded
by the hook engine. Projects created via `aipass init` auto-enroll;
these commands handle manual enrollment and revocation.
"""

from __future__ import annotations

from pathlib import Path

from aipass.cli.apps.modules import console, error, success
from aipass.hooks.apps.handlers.config import trust_registry
from aipass.hooks.apps.handlers.config.trust_registry import (
    enroll,
    read_registry,
    revoke,
)
from aipass.hooks.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.help_flag import wants_help
from aipass.prax import logger

COMMAND = "trust"
_COMMAND_REVOKE = "revoke"


def print_introspection() -> None:
    """Display the current trusted-project registry."""
    from rich.table import Table

    registry = read_registry()
    projects = registry.get("projects", {})

    console.print()
    console.print("[bold cyan]aipass trust[/bold cyan] — trusted-project registry")
    console.print()

    if not projects:
        console.print("[dim]No projects enrolled.[/dim]")
    else:
        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Project", style="cyan")
        table.add_column("Hash", style="dim", max_width=24)
        table.add_column("Enrolled")
        for path, entry in projects.items():
            short_hash = entry.get("config_hash", "")[:18] + "..."
            table.add_row(path, short_hash, entry.get("enrolled", ""))
        console.print(table)

    console.print()
    console.print("[dim]Use 'aipass trust <path>' to enroll or 'aipass revoke <path>' to remove.[/dim]")
    console.print()


def print_help() -> None:
    """Print usage help for the trust/revoke commands."""
    console.print()
    console.print("[bold cyan]aipass trust / revoke[/bold cyan] — trusted-project registry")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  [green]aipass trust[/green]            [dim]# Show enrolled projects[/dim]")
    console.print(
        "  [green]aipass trust <path>[/green]     [dim]# Enroll a project (requires .aipass/hooks.json)[/dim]"
    )
    console.print("  [green]aipass revoke <path>[/green]    [dim]# Remove a project from the registry[/dim]")
    console.print(
        "  [green]aipass trust prune[/green]      [dim]# Drop entries whose project path no longer exists[/dim]"
    )
    console.print()


def _do_trust(args: list[str]) -> bool:
    """Execute the trust enrollment for a given path."""
    target = Path(args[0]).resolve()
    if not target.is_dir():
        error(f"Not a directory: {target}")
        return True
    hooks_path = target / ".aipass" / "hooks.json"
    if not hooks_path.is_file():
        error(f"No .aipass/hooks.json found in {target}")
        return True
    if enroll(str(target)):
        success(f"Enrolled {target}")
        logger.info("[AIPASS] trust: enrolled %s", target)
    else:
        error(f"Failed to enroll {target}")
    return True


def _do_prune() -> bool:
    """Drop registry entries whose project path no longer exists on disk."""
    registry = read_registry()
    projects = registry.get("projects", {})
    stale = [path for path in projects if not Path(path).exists()]
    for path in stale:
        del projects[path]
    if stale:
        json_handler.write_json_file(trust_registry.REGISTRY_PATH, registry)
        json_handler.log_operation("prune", {"pruned_count": len(stale)}, module_name="trust")
        success(f"Pruned {len(stale)} stale entr{'y' if len(stale) == 1 else 'ies'} from the trust registry.")
        logger.info("[AIPASS] trust: pruned %d stale entries", len(stale))
    else:
        console.print("[dim]No stale entries found.[/dim]")
    return True


def _do_revoke(args: list[str]) -> bool:
    """Execute the revocation for a given path."""
    target = Path(args[0]).resolve()
    if revoke(str(target)):
        success(f"Revoked {target}")
        logger.info("[AIPASS] revoke: removed %s", target)
    else:
        console.print(f"[dim]{target} was not in the registry.[/dim]")
    return True


def handle_command(command: str, args: list[str]) -> bool:
    """Route trust/revoke subcommands. Returns True if handled."""
    if command == COMMAND:
        if not args:
            print_introspection()
            return True
        if wants_help(args):
            print_help()
            return True
        if args[0] == "--info":
            print_introspection()
            return True
        if args[0] == "prune":
            return _do_prune()
        return _do_trust(args)
    if command == _COMMAND_REVOKE:
        if not args or wants_help(args):
            print_help()
            return True
        return _do_revoke(args)
    return False
