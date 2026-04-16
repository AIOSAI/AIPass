# =================== AIPass ====================
# Name: registry_monitor.py
# Description: Registry auto-healing and file watching module
# Version: 2.1.0
# Created: 2025-11-21
# Modified: 2025-11-21
# =============================================

"""
Registry Monitor Module - Auto-Healing PLAN Registry

Thin orchestrator for filesystem monitoring and registry healing.
All business logic delegated to handlers/registry/monitor_ops.py.

Architecture (v2.0):
- PlanFileWatcher detects filesystem events via Python watchdog
- Events are fired via the trigger event bus (plan_file_created, plan_file_deleted, plan_file_moved)
- Trigger handlers in trigger/apps/handlers/events/plan_file.py update the registry
- Decoupled: Flow fires events, Trigger handles reactions

Features:
- Real-time file watching via Python watchdog
- Auto-detect file create/move/delete events
- Scan and heal registry (orphaned entries, missing files)
- Duplicate plan detection with auto-renumbering
- Metadata preservation on file moves

Usage:
    From flow.py: flow registry_monitor [scan|start|stop|status]
    Standalone: drone @flow registry [command]

Commands:
    scan    - One-time scan and heal registry
    heal    - Alias for scan
    start   - Start watchdog monitoring (runs until Ctrl+C)
    stop    - Stop watchdog monitoring
    status  - Show monitoring status
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

# External: Prax logger
from aipass.prax.apps.modules.logger import system_logger as logger

# JSON handler for operation tracking
from aipass.flow.apps.handlers.json import json_handler

# CLI services for display
from aipass.cli.apps.modules import console, error, warning

# Registry handlers
from aipass.flow.apps.handlers.registry.load_registry import load_registry

# Implementation handler
from aipass.flow.apps.handlers.registry.monitor_ops import (
    scan_plan_files_impl,
    start_monitoring_impl,
    stop_monitoring_impl,
    get_status_impl,
)

# =============================================
# CONFIGURATION
# =============================================

MODULE_NAME = "registry_monitor"


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()
ECOSYSTEM_ROOT = REPO_ROOT  # Scan from repo root


# =============================================
# THIN ORCHESTRATION WRAPPERS
# =============================================


def scan_plan_files() -> Dict[str, Any]:
    """
    Scan ecosystem for PLAN files and fire events to heal registry (thin orchestrator)

    Delegates to monitor_ops handler for implementation.

    Returns:
        Dict with scan results and event stats
    """
    return scan_plan_files_impl(
        ecosystem_root=ECOSYSTEM_ROOT,
        load_registry=load_registry,
    )


def start_monitoring():
    """Start PLAN file monitoring with watchdog (thin orchestrator)

    Returns:
        True if started successfully, False otherwise
    """
    result = start_monitoring_impl(ecosystem_root=ECOSYSTEM_ROOT)
    # Module handles display
    status = result.get("status", "")
    if status == "already_running":
        warning("Monitor is already running")
    elif status == "started":
        console.print(f"[green]OK[/green] {result['message']}")
    elif status == "error":
        error(result["message"])
    return result.get("success", False)


def stop_monitoring():
    """Stop PLAN file monitoring (thin orchestrator)

    Returns:
        True if stopped successfully, False otherwise
    """
    result = stop_monitoring_impl()
    # Module handles display
    status = result.get("status", "")
    if status == "stopped":
        console.print("[green]OK[/green] Monitor stopped")
    elif status == "not_running":
        warning("Monitor is not running")
    return result.get("success", False)


def get_status() -> Dict[str, Any]:
    """Get monitoring status (thin orchestrator)"""
    return get_status_impl(
        ecosystem_root=ECOSYSTEM_ROOT,
        load_registry=load_registry,
    )


# =============================================
# COMMAND HANDLER
# =============================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle command routing for registry_monitor module

    Commands:
        scan    - One-time scan and heal
        heal    - Alias for scan
        start   - Start watchdog monitoring
        stop    - Stop watchdog monitoring
        status  - Show monitoring status

    Args:
        command: Command name
        args: Additional arguments

    Returns:
        True if command handled successfully, False otherwise
    """
    # Check if this is our command
    if command != "registry":
        return False

    if not args:
        print_introspection()
        return True

    # Handle help flag
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # Get subcommand
    subcommand = args[0] if args else "status"

    # Log the operation
    json_handler.log_operation("registry_monitor", {"command": command, "subcommand": subcommand})

    if subcommand in ["scan", "heal"]:
        console.print("[bold]Scanning for PLAN files...[/bold]")
        result = scan_plan_files()

        console.print()
        console.print("[green]✓[/green] Scan complete")
        console.print(f"  • Total plans: {result['total_plans']}")
        console.print(f"  • Added: {len(result['added'])}")
        console.print(f"  • Updated: {len(result['updated'])}")
        console.print(f"  • Removed: {len(result['removed'])}")
        console.print(f"  • Renumbered: {len(result['renumbered'])}")

        if result["healing_performed"]:
            change_count = len(result["added"]) + len(result["updated"]) + len(result["removed"])
            warning(
                f"Registry scan found {change_count} mismatch(es) — trigger event handlers not wired, no changes applied"
            )
        else:
            console.print("\n[dim]No changes needed - registry is healthy[/dim]")

        console.print()
        return True

    elif subcommand == "start":
        console.print("[bold]Starting registry monitor...[/bold]")
        console.print()

        # Run initial scan before starting monitor
        console.print("[dim]Running initial scan...[/dim]")
        scan_result = scan_plan_files()
        console.print(f"[dim]Found {scan_result['total_plans']} PLAN files[/dim]")
        console.print()

        success = start_monitoring()
        if success:
            console.print()
            warning("Monitor is running. Press Ctrl+C to stop.")
            console.print()

            # Keep script alive
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("[registry_monitor] Keyboard interrupt received, stopping monitor")
                console.print()
                console.print("[bold]Stopping monitor...[/bold]")
                stop_monitoring()
                console.print()

        return success

    elif subcommand == "stop":
        return stop_monitoring()

    elif subcommand == "status":
        status = get_status()

        console.print()
        console.print("[bold cyan]Registry Monitor Status[/bold cyan]")
        console.print()
        console.print(f"  • Version: {status['version']}")
        console.print(
            f"  • Monitoring: {'[green]Active[/green]' if status['monitoring_active'] else '[yellow]Inactive[/yellow]'}"
        )
        console.print(f"  • Watch location: {status['watch_location']}")
        console.print(f"  • Total plans: {status['total_plans']}")
        console.print(f"  • Open plans: {status['open_plans']}")
        console.print(f"  • Ignored folders: {status['ignore_folders']}")
        console.print()
        console.print("[dim]Commands: scan | start | stop | status[/dim]")
        console.print()

        return True

    else:
        error(f"Unknown subcommand: {subcommand}")
        console.print()
        console.print("Available commands:")
        console.print("  • scan    - One-time scan and heal registry")
        console.print("  • heal    - Alias for scan")
        console.print("  • start   - Start watchdog monitoring")
        console.print("  • stop    - Stop watchdog monitoring")
        console.print("  • status  - Show monitoring status")
        console.print()
        return False


# =============================================
# INTROSPECTION
# =============================================


def print_introspection():
    """Display module info and usage"""
    console.print()
    console.print("[bold cyan]registry_monitor Module[/bold cyan]")
    console.print()

    console.print("[yellow]Purpose:[/yellow]")
    console.print("  Auto-healing registry that keeps PLAN files synchronized with filesystem")
    console.print()

    console.print("[yellow]Features:[/yellow]")
    console.print("  • Real-time file watching (watchdog)")
    console.print("  • Auto-detect create/move/delete events")
    console.print("  • Scan and heal registry")
    console.print("  • Duplicate detection with auto-renumbering")
    console.print("  • Metadata preservation on moves")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print("  • scan    - One-time scan and heal registry")
    console.print("  • heal    - Alias for scan")
    console.print("  • start   - Start watchdog monitoring (runs until Ctrl+C)")
    console.print("  • stop    - Stop watchdog monitoring")
    console.print("  • status  - Show monitoring status")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  • [cyan]handlers/registry/monitor_ops.py (implementation)[/cyan]")
    console.print("  • [cyan]handlers/registry/load_registry.py[/cyan]")
    console.print("  • [cyan]handlers/registry/save_registry.py[/cyan]")
    console.print()

    console.print("[dim]Run 'drone @flow registry --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for registry_monitor module"""
    console.print()
    console.print("[bold cyan]registry_monitor[/bold cyan] — Auto-healing PLAN registry")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow registry <subcommand>")
    console.print()
    console.print("[yellow]SUBCOMMANDS:[/yellow]")
    console.print("  scan      One-time scan and heal")
    console.print("  heal      Alias for scan")
    console.print("  start     Start persistent watchdog monitoring")
    console.print("  stop      Stop watchdog monitoring")
    console.print("  status    Check monitoring status")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow registry scan[/dim]             # One-time scan and heal")
    console.print("  [dim]drone @flow registry start[/dim]            # Start persistent monitoring")
    console.print("  [dim]drone @flow registry status[/dim]           # Check monitoring status")
    console.print("  [dim]drone @flow registry stop[/dim]             # Stop monitoring")
    console.print()


# =============================================
# STANDALONE EXECUTION
# =============================================

if __name__ == "__main__":
    # Show introspection when run without arguments
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    # Handle help flag
    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    # Confirm logger connection
    logger.info("Prax logger connected to registry_monitor")

    # Log standalone execution
    json_handler.log_operation("registry_monitor", {"command": "standalone"})

    # Call handle_command
    args = sys.argv[1:] if len(sys.argv) > 1 else []
    result = handle_command("registry_monitor", args)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)
