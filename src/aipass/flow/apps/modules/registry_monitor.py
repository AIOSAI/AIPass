# =================== AIPass ====================
# Name: registry_monitor.py
# Description: Registry auto-healing module
# Version: 3.1.0
# Created: 2025-11-21
# Modified: 2026-07-29
# =============================================

"""
Registry Monitor Module - Auto-Healing PLAN Registry

Thin orchestrator for registry scanning and healing.
All business logic delegated to handlers/registry/monitor_ops.py.

Features:
- Scan and heal registry (orphaned entries, missing files)
- Duplicate plan detection with auto-renumbering
- Registry doctrine self-heal (number collisions, unregistered files,
  wrong-prefix rows) applied directly on every scan
- Registry status reporting

Usage:
    From flow.py: flow registry_monitor [scan|status]
    Standalone: drone @flow registry [command]

Commands:
    scan    - One-time scan and heal registry
    heal    - Alias for scan
    status  - Show registry status
"""

# ruff: noqa: E402
import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

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
from aipass.cli.apps.modules import console, error, success, warning

# Registry handlers
from aipass.flow.apps.handlers.registry.load_registry import load_registry

# Implementation handler
from aipass.flow.apps.handlers.registry.monitor_ops import (
    scan_plan_files_impl,
    get_status_impl,
)

# Registry doctrine self-heal (number collisions / unregistered files / wrong-prefix rows)
from aipass.flow.apps.handlers.registry.heal_registry import heal_registry_doctrine_impl

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
    Scan ecosystem for PLAN files and heal the registry (thin orchestrator)

    Two passes, both delegated to handlers:
    1. monitor_ops.scan_plan_files_impl — detection + duplicate renumbering
    2. heal_registry.heal_registry_doctrine_impl — direct, synchronous
       registry repair for the three doctrine cases (number collision,
       unregistered file, wrong-prefix row). Runs on every scan so these
       never need a manual JSON fix again.

    Returns:
        Dict with scan results, event stats, and doctrine heal results
    """
    result = scan_plan_files_impl(
        ecosystem_root=ECOSYSTEM_ROOT,
        load_registry=load_registry,
    )

    heal_result = heal_registry_doctrine_impl(ecosystem_root=ECOSYSTEM_ROOT)
    result["doctrine_healed"] = heal_result["healed_count"]
    result["doctrine_heals"] = heal_result["healed"]

    return result


def get_status() -> Dict[str, Any]:
    """Get registry status (thin orchestrator)"""
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
        status  - Show registry status

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
        success("Scan complete")
        console.print(f"  • Total plans: {result['total_plans']}")
        console.print(f"  • Added: {len(result['added'])}")
        console.print(f"  • Updated: {len(result['updated'])}")
        console.print(f"  • Removed: {len(result['removed'])}")
        console.print(f"  • Renumbered: {len(result['renumbered'])}")
        console.print(f"  • Doctrine healed: {result.get('doctrine_healed', 0)}")

        if result.get("doctrine_healed", 0) > 0:
            for heal in result.get("doctrine_heals", []):
                prefix = heal.get("prefix", "?")
                number = heal.get("number", "?")
                console.print(f"    - {prefix}-{number}: {heal.get('action', 'unknown')}")

        if result["healing_performed"]:
            change_count = len(result["added"]) + len(result["updated"]) + len(result["removed"])
            warning(
                f"Registry scan found {change_count} mismatch(es) — "
                "trigger event handlers not wired, no changes applied"
            )
        else:
            console.print("\n[dim]No changes needed - registry is healthy[/dim]")

        console.print()
        return True

    elif subcommand == "status":
        status = get_status()

        console.print()
        console.print("[bold cyan]Registry Status[/bold cyan]")
        console.print()
        console.print(f"  • Version: {status['version']}")
        console.print(f"  • Watch location: {status['watch_location']}")
        console.print(f"  • Total plans: {status['total_plans']}")
        console.print(f"  • Open plans: {status['open_plans']}")
        console.print(f"  • Ignored folders: {status['ignore_folders']}")
        console.print()
        console.print("[dim]Commands: scan | status[/dim]")
        console.print()

        return True

    else:
        error(f"Unknown subcommand: {subcommand}")
        console.print()
        console.print("Available commands:")
        console.print("  • scan    - One-time scan and heal registry")
        console.print("  • heal    - Alias for scan")
        console.print("  • status  - Show registry status")
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
    console.print("  • Scan and heal registry")
    console.print("  • Duplicate detection with auto-renumbering")
    console.print("  • Doctrine self-heal (collisions, unregistered files, wrong-prefix rows)")
    console.print("  • Registry status reporting")
    console.print()

    console.print("[yellow]Commands:[/yellow]")
    console.print("  • scan    - One-time scan and heal registry")
    console.print("  • heal    - Alias for scan")
    console.print("  • status  - Show registry status")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print("  • [cyan]handlers/registry/monitor_ops.py (implementation)[/cyan]")
    console.print("  • [cyan]handlers/registry/heal_registry.py (doctrine self-heal)[/cyan]")
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
    console.print("  status    Show registry status")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow registry scan[/dim]             # One-time scan and heal")
    console.print("  [dim]drone @flow registry status[/dim]           # Check registry status")
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
