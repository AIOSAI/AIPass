# =================== AIPass ====================
# Name: registry_monitor.py
# Description: Registry auto-healing module
# Version: 3.4.0
# Created: 2025-11-21
# Modified: 2026-10-17
# =============================================

"""
Registry Monitor Module - Auto-Healing PLAN Registry

Thin orchestrator for registry scanning and healing.
All business logic delegated to handlers/registry/monitor_ops.py.

Features:
- Scan and heal registry (orphaned entries, missing files)
- Duplicate plan detection, reported and never renamed
- Registry doctrine self-heal (number collisions, unregistered files,
  wrong-prefix rows, orphaned locations) applied directly on every scan
- Quarantine list for locations the healer refuses to guess at, surfaced
  by `status` for a human ruling
- Registry status reporting

Usage:
    From flow.py: flow registry_monitor [scan|status]
    Standalone: drone @flow registry [command]

Commands:
    scan    - One-time scan and heal registry
    heal    - Alias for scan
    status  - Show registry status
"""

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

from aipass.flow.apps.handlers.repo_root import find_repo_root, module_file

_PKG_ROOT = module_file(__file__).parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.flow.apps.handlers.cli.arg_gate import UnknownArgument, refuse_unknown
from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler

from aipass.cli.apps.modules import console, error, success, warning

from aipass.flow.apps.handlers.registry.load_registry import RegistryUnreadableError, load_registry

from aipass.flow.apps.handlers.registry.monitor_ops import (
    scan_plan_files_impl,
    get_status_impl,
)

from aipass.flow.apps.handlers.registry.heal_registry import (
    find_quarantined_locations,
    heal_registry_doctrine_impl,
)


MODULE_NAME = "registry_monitor"

REGISTRY_SUBCOMMANDS = ("scan", "heal", "status")


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json)."""
    return find_repo_root(caller="registry_monitor")


REPO_ROOT = _find_repo_root()
ECOSYSTEM_ROOT = REPO_ROOT  # Scan from repo root


def scan_plan_files() -> Dict[str, Any]:
    """Scan ecosystem for PLAN files and heal the registry (thin orchestrator)"""
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


def handle_command(command: str, args: List[str]) -> bool:
    """Handle command routing for registry_monitor module"""
    if command != "registry":
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere in args: `registry scan --help` must never reach the scan, which WRITES.
    if wants_help(args):
        print_help()
        return True

    subcommand = args[0] if args else "status"

    json_handler.log_operation("registry_monitor", {"command": command, "subcommand": subcommand})

    if subcommand in ["scan", "heal"]:
        console.print("[bold]Scanning for PLAN files...[/bold]")
        try:
            result = scan_plan_files()
        except RegistryUnreadableError as exc:
            error(f"Registry scan refused: {exc}")
            return True

        console.print()
        success("Scan complete")
        console.print(f"  • Total plans: {result['total_plans']}")
        console.print(f"  • Added: {len(result['added'])}")
        console.print(f"  • Updated: {len(result['updated'])}")
        console.print(f"  • Removed: {len(result['removed'])}")
        console.print(f"  • Duplicates (reported, not renamed): {len(result['duplicates'])}")
        for dup in result["duplicates"]:
            console.print(f"    - {dup['prefix']}-{dup['number']}: {', '.join(dup['paths'])}")
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
        try:
            status = get_status()
        except RegistryUnreadableError as exc:
            error(f"Registry status refused: {exc}")
            return True

        console.print()
        console.print("[bold cyan]Registry Status[/bold cyan]")
        console.print()
        console.print(f"  • Version: {status['version']}")
        console.print(f"  • Watch location: {status['watch_location']}")
        console.print(f"  • Total plans: {status['total_plans']}")
        console.print(f"  • Open plans: {status['open_plans']}")
        console.print(f"  • Ignored folders: {status['ignore_folders']}")

        quarantined = find_quarantined_locations()
        console.print()
        if quarantined:
            warning(f"{len(quarantined)} plan row(s) quarantined — location not attributable to a live citizen")
            by_location: Dict[str, List[str]] = {}
            for row in quarantined:
                by_location.setdefault(f"{row['location'] or '<none>'} — {row['reason']}", []).append(row["plan_id"])
            for label, plan_ids in sorted(by_location.items(), key=lambda kv: -len(kv[1])):
                shown = ", ".join(plan_ids[:4]) + (f" +{len(plan_ids) - 4} more" if len(plan_ids) > 4 else "")
                console.print(f"    [yellow]•[/yellow] {label}")
                console.print(f"      [dim]{shown}[/dim]")
            console.print()
            console.print("[dim]These await a human ruling — the healer refuses to guess an owner.[/dim]")
        else:
            console.print("[dim]No quarantined plan locations[/dim]")

        console.print()
        console.print("[dim]Commands: scan | status[/dim]")
        console.print()

        return True

    else:
        # Exit here, never return False: False makes flow.py print a second "Unknown command".
        try:
            refuse_unknown(subcommand, door="registry", valid=REGISTRY_SUBCOMMANDS, noun="subcommand")
        except UnknownArgument as exc:
            error(exc.message, suggestion=exc.usage)
            raise SystemExit(1) from exc


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
    console.print("  • Duplicate detection (reported, never renamed)")
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


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print_introspection()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    logger.info("Prax logger connected to registry_monitor")

    json_handler.log_operation("registry_monitor", {"command": "standalone"})

    args = sys.argv[1:] if len(sys.argv) > 1 else []
    result = handle_command("registry_monitor", args)

    if result:
        sys.exit(0)
    else:
        sys.exit(1)
