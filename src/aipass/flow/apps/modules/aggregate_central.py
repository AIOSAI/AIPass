# =================== AIPass ====================
# Name: aggregate_central.py
# Description: Aggregate Central Plans Module
# Version: 1.5.0
# Created: 2025-11-30
# Modified: 2026-10-23
# =============================================

"""
Aggregate Central Plans Module

Thin orchestrator for central plans aggregation.
All business logic delegated to handlers/plan/aggregate_ops.py.

Features:
- Validates all plans in branches.* sections have files on disk
- Auto-closes plans with missing files in their branch registries
- Aggregates active plans from all branches into top-level active_plans array
- Builds recently_closed array from all branches
- Updates statistics across all branches
- Preserves unknown branch sections

Usage:
    from aipass.flow.apps.modules.aggregate_central import aggregate_central
    success = aggregate_central()

Standalone:
    drone @flow aggregate
    drone @flow aggregate --heal
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
from typing import List

from aipass.flow.apps.handlers.repo_root import find_repo_root, module_file

_PKG_ROOT = module_file(__file__).parents[3]  # file.py -> modules/ -> apps/ -> flow/ -> aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

from aipass.cli.apps.modules import console, error
from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.flow.apps.handlers.cli.arg_gate import UnknownArgument, refuse_unknown
from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler

from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_all_branch_dashboards
from aipass.flow.apps.handlers.plan.aggregate_ops import aggregate_central_impl
from aipass.flow.apps.handlers.registry.save_registry import registry_lock

MODULE_NAME = "aggregate_central"

# One list so the refusal and the parsing cannot drift apart.
AGGREGATE_FLAGS = ("--heal", "--no-heal", "--sweep-cards")


def _find_repo_root() -> Path:
    """Walk up to the repo root (the directory holding AIPASS_REGISTRY.json)."""
    return find_repo_root(caller="aggregate_central")


_REPO_ROOT = _find_repo_root()
AI_CENTRAL_DIR = _REPO_ROOT / ".ai_central"
CENTRAL_FILE = AI_CENTRAL_DIR / "PLANS.central.json"


def aggregate_central(heal: bool = True) -> bool:
    """Aggregate and validate central plans (thin orchestrator)"""
    try:
        with registry_lock():
            return aggregate_central_impl(
                heal=heal,
                central_file=CENTRAL_FILE,
                central_dir=AI_CENTRAL_DIR,
            )
    except TimeoutError as exc:
        logger.error("[aggregate_central] %s", exc)
        return False


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]aggregate_central Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/plan/[/cyan]")
    console.print("    [dim]- aggregate_ops.py (aggregate_central_impl — aggregation and healing logic)[/dim]")
    console.print()
    console.print("  [cyan]handlers/dashboard/[/cyan]")
    console.print("    [dim]- push_branch_dashboard.py (push_flow_to_all_branch_dashboards — --sweep-cards)[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow aggregate --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for aggregate_central module"""
    console.print()
    console.print("[bold cyan]aggregate_central[/bold cyan] — Central plans aggregation and self-healing")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow aggregate \\[options]")
    console.print()
    console.print("[yellow]OPTIONS:[/yellow]")
    console.print("  --heal          Auto-close missing plans [dim](default)[/dim]")
    console.print("  --no-heal       Validation only")
    console.print("  --sweep-cards   Re-push the flow section to every branch dashboard")
    console.print()
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow aggregate[/dim]                 # Aggregate with healing (default)")
    console.print("  [dim]drone @flow aggregate --no-heal[/dim]       # Validation only")
    console.print("  [dim]drone @flow aggregate --sweep-cards[/dim]   # Heal every branch card at once")
    console.print()
    console.print("[dim]Cards are written on plan events, so a branch that files no plan keeps[/dim]")
    console.print("[dim]whatever shape it last received. --sweep-cards lands a change fleet-wide.[/dim]")
    console.print()


def handle_command(command: str, args: List[str]) -> bool:
    """Handle module commands"""
    if command != "aggregate":
        return False

    if not args:
        print_introspection()
        return True

    if wants_help(args):
        print_help()
        return True

    # Refused by name: an ignored typo would run the real cross-branch write and report success.
    unknown = [token for token in args if token not in AGGREGATE_FLAGS]
    if unknown:
        try:
            refuse_unknown(unknown[0], door="aggregate", valid=AGGREGATE_FLAGS, noun="argument")
        except UnknownArgument as exc:
            error(exc.message, suggestion=exc.usage)
            raise SystemExit(1) from exc

    json_handler.log_operation("central_aggregated", {"command": command, "args": args})

    heal = True
    if "--no-heal" in args:
        heal = False

    result = aggregate_central(heal=heal)
    if result:
        console.print("[green]Central plans aggregated successfully[/green]")
    else:
        logger.error("[aggregate_central] Central plans aggregation failed")
        error("Central plans aggregation failed")

    if "--sweep-cards" in args:
        counts = push_flow_to_all_branch_dashboards()
        console.print(
            f"[green]Card sweep:[/green] {counts['pushed']} pushed, "
            f"{counts['skipped']} skipped (no dashboard), {counts['failed']} failed"
        )
        result = result and counts["failed"] == 0

    return result


def main():
    """Main entry point for standalone execution"""
    if len(sys.argv) > 1 and sys.argv[1] in ["--help", "-h", "help"]:
        print_help()
        sys.exit(0)

    if len(sys.argv) < 2:
        console.print("Usage: drone @flow aggregate \\[options]")
        console.print("Commands:")
        console.print("  aggregate         - Aggregate central plans (with healing)")
        console.print("  aggregate --heal  - Aggregate with explicit healing")
        console.print("  aggregate --no-heal - Aggregate without healing")
        console.print()
        console.print("Run with --help for detailed information")
        sys.exit(1)

    command = sys.argv[1]
    args = sys.argv[2:]

    success = handle_command(command, args)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
