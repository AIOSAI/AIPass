# =================== AIPass ====================
# Name: memory.py
# Description: Entry point CLI for drone @memory
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Memory System - Central Memory Archive & Rollover System

PURPOSE: Manages memory rollover, archival, and retrieval across all AIPass branches.

ARCHITECTURE:
- Entry point auto-discovers modules
- Modules orchestrate workflow by calling handlers
- Handlers implement domain-specific business logic
"""

import sys
import time
import signal

from pathlib import Path
from typing import List, Any
import importlib

from rich.panel import Panel
from rich import box
from rich.table import Table

from aipass.prax import logger
from aipass.cli.apps.modules import console, error

# =============================================================================
# INFRASTRUCTURE SETUP
# =============================================================================

# Package name for module discovery (relative imports within this package)
_PACKAGE_BASE = "aipass.memory.apps.modules"


# =============================================================================
# INTROSPECTION DISPLAY
# =============================================================================


def print_introspection():
    """Display discovered modules and status"""
    console.print()
    console.print("[bold cyan]Memory - Central Memory Archive System[/bold cyan]")
    console.print()
    console.print("[dim]Manages memory rollover and archival across AIPass branches[/dim]")
    console.print()

    # Discover modules
    modules = discover_modules()

    console.print(f"[bold cyan]Discovered Modules:[/bold cyan] {len(modules)}")
    console.print()

    for module in modules:
        module_name = module.__name__.split(".")[-1]
        console.print(f"  [cyan]*[/cyan] {module_name}")

    if not modules:
        console.print("  [dim]No modules discovered yet[/dim]")

    console.print()
    console.print("[dim]Run 'drone @memory help' for usage information[/dim]")
    console.print()


# =============================================================================
# HELP SYSTEM
# =============================================================================


def print_help():
    """Display Rich-formatted help"""

    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Memory - Central Memory Archive System[/bold cyan]\n[dim]Vector search, memory rollover, and fragmented memory for AIPass[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )
    console.print()

    # What is Memory section
    what_content = (
        "Memory is the [bold]central memory archive[/bold] that:\n\n"
        "  [green]>[/green] Provides semantic search across all branch memories\n"
        "  [green]>[/green] Archives memories when branches hit rollover limits"
    )
    console.print(
        Panel(what_content, title="[bold cyan]What is Memory?[/bold cyan]", border_style="dim", box=box.ROUNDED)
    )
    console.print()

    console.print("[bold cyan]AVAILABLE COMMANDS:[/bold cyan]")
    console.print()

    # Commands table showing actual drone commands
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Command", style="green")
    table.add_column("Description", style="dim")

    # Core commands — only those with backing modules
    table.add_row("rollover", "Show rollover module introspection")
    table.add_row("rollover run", "Execute memory rollover")
    table.add_row("rollover status", "Show rollover statistics")
    table.add_row("rollover check", "Dry run — check what needs rollover")
    table.add_row("rollover sync-lines", "Update line count metadata")
    table.add_row("search <query>", "Semantic search across all branch memories")
    table.add_row("symbolic <subcommand>", "Symbolic/fragmented memory extraction and search")
    table.add_row("templates <subcommand>", "Living template push, diff, and status")
    table.add_row("verify <plan_label>", "Check if a plan is vectorized in ChromaDB")
    table.add_row("watch", "Start memory watcher (auto-rollover on changes)")

    console.print(table)

    console.print()
    console.print("-" * 70)
    console.print()

    console.print("[bold cyan]USAGE:[/bold cyan]")
    console.print()
    console.print("  [bold]Via Drone (recommended):[/bold]")
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
    console.print("  [cyan]--branch BRANCH[/cyan]    Filter by branch (e.g., SEEDGO, CLI)")
    console.print("  [cyan]--type TYPE[/cyan]        Filter by memory type (observations, local)")
    console.print("  [cyan]--n N[/cyan]              Number of results (default: 5)")
    console.print()
    console.print("  [bold]Example:[/bold]")
    console.print('    [dim]drone @memory search "registry bugs" --branch SEEDGO --n 10[/dim]')
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

    console.print("Commands: search, rollover [run|status|check|sync-lines], symbolic, templates, verify, watch")
    console.print()


# =============================================================================
# MODULE DISCOVERY
# =============================================================================

MODULES_DIR = Path(__file__).parent / "modules"


def discover_modules() -> List[Any]:
    """
    Auto-discover modules in modules/ directory

    Pattern: Any .py file in modules/ that implements handle_command()
    gets automatically discovered and registered.

    Returns:
        List of module objects with handle_command() method
    """
    modules = []

    if not MODULES_DIR.exists():
        return modules

    for file_path in MODULES_DIR.glob("*.py"):
        if file_path.name.startswith("_"):  # Skip __init__.py, __pycache__, etc.
            continue

        module_name = f"{_PACKAGE_BASE}.{file_path.stem}"

        try:
            module = importlib.import_module(module_name)

            # Duck typing: If it has handle_command(), it's a module
            if hasattr(module, "handle_command"):
                modules.append(module)
                logger.info(f"[memory] Discovered module: {module_name}")
        except Exception as e:
            logger.error(f"[memory] Failed to load module {module_name}: {e}")

    return modules


def route_command(command: str, args: List[str], modules: List[Any]) -> bool:
    """
    Route command to appropriate module

    Pattern: Each module's handle_command() returns True if it handled the command

    Args:
        command: Command name (e.g., 'rollover', 'search', 'status')
        args: Additional arguments
        modules: List of discovered modules

    Returns:
        True if command was handled, False otherwise
    """
    # Built-in commands handled by entry point
    if command == "watch":
        start_watch()
        return True

    for module in modules:
        try:
            if module.handle_command(command, args):
                return True
        except Exception as e:
            logger.error(f"[memory] Module {module.__name__} error: {e}")

    return False


# =============================================================================
# WATCH MODE
# =============================================================================


def start_watch() -> None:
    """
    Start memory watcher - monitors branch memory files for auto-rollover

    Watches all branches from AIPASS_REGISTRY.json. When a memory file
    exceeds 600 lines, automatically triggers rollover.

    Press Ctrl+C to stop.
    """
    from ..handlers.monitor.memory_watcher import (  # type: ignore[import-not-found]
        start_memory_watcher,
        stop_memory_watcher,
    )
    from ..handlers.monitor.detector import get_rollover_stats  # type: ignore[import-not-found]

    # Signal handler for graceful shutdown
    def signal_handler(sig, frame):
        """Handle SIGINT for graceful watcher shutdown."""
        console.print("\n")
        console.print("[dim]Stopping watcher...[/dim]")
        stop_memory_watcher()
        console.print("[green]>[/green] Watcher stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    console.print()
    console.print(Panel.fit("[bold cyan]Memory - Watch Mode[/bold cyan]", border_style="cyan", box=box.ROUNDED))
    console.print()

    # Start the watcher
    result = start_memory_watcher()

    if not result.get("success"):
        error(f"Failed to start watcher: {result.get('error')}")
        return

    console.print(f"[green]>[/green] Watching {result.get('count', 0)} branch directories")
    console.print("[dim]Auto-rollover enabled when files exceed limits[/dim]")
    console.print("[dim]Press Ctrl+C to stop[/dim]")
    console.print()

    # Show initial status
    stats = get_rollover_stats()
    if stats.get("success"):
        ready = stats.get("files_ready", 0)
        total = stats.get("files_checked", 0)
        status_marker = "[red]![/red]" if ready > 0 else "[green]OK[/green]"
        console.print(f"{status_marker} Current: {total} files monitored, {ready} ready for rollover")
        console.print()

    # Keep running until Ctrl+C
    console.print("[dim]Watcher active. Waiting for file changes...[/dim]")
    while True:
        time.sleep(1)


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main():
    """Main entry point - routes commands or shows help"""

    # Parse arguments
    args = sys.argv[1:]

    # Show introspection when run without arguments
    if len(args) == 0:
        print_introspection()
        return

    # Version flag
    if args[0] in ["--version", "-V"]:
        console.print("memory v1.0.0")
        return

    # Show help only for explicit help flags
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return

    # Command provided - try to route to modules
    modules = discover_modules()
    command = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    if route_command(command, remaining_args, modules):
        return  # Module handled it successfully
    else:
        console.print()
        error(f"Unknown command: {command}", suggestion="Run 'drone @memory help' for available commands")
        console.print()
        return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("[memory] Operation cancelled by user (KeyboardInterrupt)")
        console.print("\n\nOperation cancelled by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"[memory] Entry point error: {e}", exc_info=True)
        console.print(f"\nError: {e}")
        sys.exit(1)
