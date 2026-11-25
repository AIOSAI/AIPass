# =================== AIPass ====================
# Name: memory.py
# Description: Entry point CLI for drone @memory
# Version: 1.3.6
# Created: 2026-03-08
# Modified: 2026-11-25
# =============================================

"""
Memory System - Central Memory Archive & Rollover System
"""

__version__ = "1.3.5"

import sys

from pathlib import Path
from typing import List, Any
import importlib

from rich.panel import Panel
from rich import box
from rich.table import Table

from aipass.prax import logger
from aipass.cli import console, error, reset_command_state, resolve_exit

_PACKAGE_BASE = "aipass.memory.apps.modules"


def print_introspection():
    """Display discovered modules and status"""
    console.print()
    console.print("[bold cyan]memory - Central Memory Archive System[/bold cyan]")
    console.print()
    console.print("[dim]Manages memory rollover and archival across AIPass branches[/dim]")
    console.print()

    modules = discover_modules()

    console.print(f"[bold cyan]Discovered Modules:[/bold cyan] {len(modules)}")
    console.print()

    for module in modules:
        module_name = module.__name__.split(".")[-1]
        console.print(f"  [cyan]*[/cyan] {module_name}")

    if not modules:
        console.print("  [dim]No modules discovered yet[/dim]")

    console.print()
    console.print("[dim]Run 'drone @memory --help' for usage information[/dim]")
    console.print()


def print_help():
    """Display Rich-formatted help"""

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]memory - Central Memory Archive System[/bold cyan]\n"
            "[dim]Vector search, memory rollover, and fragmented memory for AIPass[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()

    what_content = (
        "memory is the [bold]central memory archive[/bold] that:\n\n"
        "  [green]>[/green] Gives each branch semantic search over its own local store\n"
        "  [green]>[/green] Archives memories when branches hit rollover limits"
    )
    console.print(
        Panel(what_content, title="[bold cyan]What is memory?[/bold cyan]", border_style="dim", box=box.ROUNDED)
    )
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Command", style="green")
    table.add_column("Description", style="dim")

    table.add_row("rollover", "Show rollover module introspection")
    table.add_row("rollover run", "Execute memory rollover")
    table.add_row("rollover status", "Show rollover statistics")
    table.add_row("rollover check", "Dry run — check what needs rollover")
    table.add_row("rollover push [--json]", "⚠ Reset ALL per_branch limits to defaults (system-wide)")
    table.add_row(
        "rollover backfill-local [--branch @b] [--apply]",
        "Copy global rows into each local store: @memory or the admin",
    )
    table.add_row("config get [@branch] [--json]", "Show effective rollover limits (defaults + deviations)")
    table.add_row("config set @branch <type> <n> [--json]", "Set one branch's rollover limit")
    table.add_row("config set-default <type> <n> [--json]", "Set a global default rollover limit")
    table.add_row("search <query> [--type T] [--n N]", "Semantic search of your own branch's local store")
    table.add_row("search global <query> [--branch B]", "The global store, every citizen: @memory or the admin")
    # Parked row stays so the verb explains itself instead of reading as unknown.
    table.add_row("symbolic", "⚠ PARKED 2026-08-14 — curated truth lives in Compass (drone @devpulse compass)")
    table.add_row("push [--branch @b] [--confirm]", "Trinity push — rebuild frames, archive drift, gated")
    table.add_row("templates <subcommand>", "Gold templates: spawn-templates, template-status, bump")
    table.add_row("pool process", "Process pool files + check/run rollover")
    table.add_row("pool status", "Show pool file count, config, vector stats")
    table.add_row("verify <plan_label>", "Check if a plan is vectorized in ChromaDB")
    table.add_row("lint [@branch]", "Audit .trinity entries for over-limit violations (read-only)")
    table.add_row("lint fields [@branch]", "Every string field by chars, flagging what is outside the shape")
    # A verb that exists and is not in --help is a verb nobody finds.
    table.add_row("health @branch", "Read-only branch health: rollover state + cap violations")
    table.add_row("roots", "Declared repo roots on this machine: list, init, add, remove, heal")
    # `\\[` because Rich reads `[@name]` as a markup tag and prints nothing.
    table.add_row("todo \\[@branch]", "One line: the todo pad against its count, and the backlog count")
    table.add_row("todo backlog \\[@branch]", "List a branch's todo backlog (.backup/todo/<branch>/backlog.json)")
    table.add_row("todo restore <number>", "Move one backlog todo back onto your own pad, re-numbered")
    table.add_row("watch", "Start memory watcher (auto-rollover on changes)")

    console.print(table)

    console.print()
    # Library modules other code imports; each answers only its own introspection, never a verb.
    console.print("[bold cyan]LIBRARIES:[/bold cyan] [dim](imported by code, not commands)[/dim]")
    for name, what in (
        ("fleet", "The fleet definition — who counts as a citizen, answered once"),
        ("limits", "The entry shape, the char caps and the file budgets — one door"),
        ("rollover_config", "The config verb's implementation after the split"),
        ("rollover_json", "The shared --json emitter the config verbs answer through"),
        ("governance", "Pure surfacing governance — state-in/state-out decisions"),
    ):
        console.print(f"  [green]{name:<16}[/green] [dim]{what}[/dim]")

    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [bold]Via drone (recommended):[/bold]")
    console.print('    [dim]drone @memory search "performance patterns"[/dim]')
    console.print("    [dim]drone @memory rollover status[/dim]")
    console.print("    [dim]drone @memory rollover run[/dim]")
    console.print()
    console.print("  [bold]Direct execution:[/bold]")
    console.print('    [dim]drone @memory search "query"[/dim]')
    console.print("    [dim]drone @memory rollover run[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]SEARCH OPTIONS:[/bold cyan]")
    console.print()
    console.print("  [cyan]--type TYPE[/cyan]        Filter by memory type (observations, local)")
    console.print("  [cyan]--n N[/cyan]              Number of results (default: 5)")
    console.print("  [cyan]--branch BRANCH[/cyan]    search global only: filter by branch (e.g. sentry)")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]EXAMPLES:[/bold cyan]")
    console.print()
    console.print('    [dim]drone @memory search "registry bugs" --type observations --n 10[/dim]')
    console.print("    [dim]drone @memory todo backlog[/dim]")
    console.print("    [dim]drone @memory lint[/dim]")
    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]WATCH MODE:[/bold cyan]")
    console.print()
    console.print("  [bold]Start memory file watcher:[/bold]")
    console.print("    [dim]drone @memory watch[/dim]")
    console.print("    [dim]Monitors all branches, auto-rolls when limit exceeded[/dim]")
    console.print("    [dim]Press Ctrl+C to stop[/dim]")
    console.print()

    console.print("-" * 70)
    console.print()

    console.print(
        "Commands: search, push, rollover \\[run|status|check|push|backfill-local],"
        " config \\[get|set|set-default], lint \\[fields], health, roots, fleet, governance,"
        " pool \\[process|status], templates, todo \\[backlog|restore], verify, watch"
    )
    console.print("[dim]--json: machine output on config get|set|set-default and rollover push[/dim]")
    console.print("[dim]Parked: symbolic (2026-08-14) — see drone @devpulse compass[/dim]")
    console.print()


MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> List[Any]:
    """Auto-discover modules in modules/ that implement handle_command()."""
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):  # Skip __init__.py, __pycache__, etc.
            continue

        module_name = f"{_PACKAGE_BASE}.{file_path.stem}"

        # A module that fails to import raises: its verbs must not read as "Unknown command".
        module = importlib.import_module(module_name)

        if hasattr(module, "handle_command"):
            modules.append(module)
            logger.info(f"[memory] Discovered module: {module_name}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """Route command to the first module whose handle_command() returns True; a module that raises propagates."""
    # Bare `push` is the gated trinity push, never an alias of the fleet-wide `rollover push` reset.
    for module in modules:
        if module.handle_command(command, args):
            return True

    return False


def main() -> int:
    """Main entry point; exit 0 success, 1 unroutable, 2 routed but refused (True means handled, not worked)."""
    reset_command_state()

    args = sys.argv[1:]

    if len(args) == 0:
        print_introspection()
        return 0

    if args[0] in ["--version", "-V"]:
        console.print(f"memory v{__version__}", highlight=False)
        return 0

    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return 0

    modules = discover_modules()
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if remaining_args and remaining_args[0] in ["--help", "-h"]:
        remaining_args = ["--help"]
        for module in modules:
            if module.handle_command(command, remaining_args):
                return 0
        print_help()
        return 0

    try:
        routed = route_command(command, remaining_args, modules)
    except Exception as e:
        # A module took the command and crashed in it: its failure (exit 2), never "Unknown command".
        logger.error(f"[memory] {command} failed: {type(e).__name__}: {e}")
        error(f"{command} failed: {type(e).__name__}: {e}")
        return resolve_exit(True)

    if routed:
        return resolve_exit(True)  # Routed — 0, or 2 if the module refused
    else:
        console.print()
        error(f"Unknown command: {command}", suggestion="Run 'drone @memory --help' for available commands")
        console.print()
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        logger.info("[memory] Operation cancelled by user (KeyboardInterrupt)")
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"[memory] Entry point error: {e}", exc_info=True)
        error(str(e))
        sys.exit(1)
