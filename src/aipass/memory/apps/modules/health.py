# =================== AIPass ====================
# Name: health.py
# Description: Branch health module — public API (entry-count + entry-size)
# Version: 1.1.0
# Created: 2026-08-16
# Modified: 2026-10-17
# =============================================

"""
Branch Health Module — Public API

Cross-branch surface: seedgo blocks importing another branch's handlers. Read-only.
Consumer severity: should_rollover -> INFO (auto-fires at PreCompact), never WARNING;
total_violations > 0 -> WARNING (a write got past the cap gate).
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.cli.help_flags import wants_help

from aipass.memory.apps.handlers.json.lint_handler import run_lint

# read_scope, not _read_registry: health never writes, so it reads the declared fleet incl. externals.
from aipass.memory.apps.handlers.monitor.detector import (
    RegistryUnreadable,
    _get_memory_file_path,
    check_single_file,
    read_scope,
)

__all__ = ["get_branch_health"]


def get_branch_health(branch_name: str) -> dict:
    """Combine entry-count and entry-size checks for one branch; an unreadable registry returns, never raises."""
    try:
        branches = read_scope()
    except RegistryUnreadable as e:
        logger.error(f"[health] {e}")
        return {"success": False, "error": str(e)}

    branch = None
    for candidate in branches:
        if str(candidate.get("name", "")).lower() == branch_name.lower():
            branch = candidate
            break

    if branch is None:
        return {"success": False, "error": f"Unknown branch: {branch_name}"}

    canonical_name = branch.get("name", branch_name)

    entry_count: dict = {}
    for memory_type in ("local", "observations"):
        file_path = _get_memory_file_path(branch, memory_type)
        if file_path is None:
            entry_count[memory_type] = None
            continue

        result = check_single_file(file_path)
        if not result.get("success"):
            entry_count[memory_type] = None
            continue

        if result.get("should_rollover"):
            trigger = result["trigger"]
            entry_count[memory_type] = {
                "should_rollover": True,
                "current_lines": trigger.current_lines,
                "reason": trigger.v2_reason,
            }
        else:
            entry_count[memory_type] = {
                "should_rollover": False,
                "current_lines": result.get("current_lines"),
                "reason": result.get("v2_reason", ""),
            }

    lint_result = run_lint([branch], branch_filter=canonical_name)
    entry_size = {
        "violations": lint_result.get("violations", []),
        "total_violations": lint_result.get("total_violations", 0),
    }

    json_handler.log_operation(
        "get_branch_health",
        {"branch": canonical_name},
        module_name="health",
    )

    return {
        "success": True,
        "branch": canonical_name,
        "entry_count": entry_count,
        "entry_size": entry_size,
    }


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]health Module[/bold cyan]")
    console.print("Read-only branch health — entry-count (rollover) + entry-size (cap violations)")
    console.print()
    console.print("[yellow]Command:[/yellow]")
    console.print("  drone @memory health @branch")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  get_branch_health(branch_name)")
    console.print()
    console.print("[dim]Also importable: aipass.memory.apps.modules.health[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery: ``health @branch`` renders that branch's health."""
    if command != "health":
        return False

    json_handler.log_operation("health_command", {"args": args})

    if not args:
        print_introspection()
        return True

    if wants_help(args, allow_bare_word=True):
        print_introspection()
        return True

    from aipass.cli.apps.modules import error

    if not (args[0].startswith("@") and len(args[0]) > 1):
        error(f"health: unknown subcommand '{args[0]}'")
        print_introspection()
        return True

    if len(args) > 1:
        error(f"health: unknown argument '{args[1]}' - usage: drone @memory health @branch")
        return True

    _print_health(get_branch_health(args[0][1:]))
    return True


def _print_health(result: dict) -> None:
    """Render one ``get_branch_health`` answer: a refusal through ``error()``, else the facts."""
    from aipass.cli.apps.modules import console, error, warning

    if not result.get("success"):
        error(f"health: {result.get('error')}")
        return

    console.print()
    console.print(f"[bold cyan]@{result['branch']} health[/bold cyan]")
    for memory_type, row in result["entry_count"].items():
        if row is None:
            console.print(f"  {memory_type}.json: not found")
        elif row["should_rollover"]:
            console.print(f"  {memory_type}.json: rollover due - {row['reason']}")
        else:
            console.print(f"  {memory_type}.json: ok ({row['current_lines']} lines)")

    total = result["entry_size"]["total_violations"]
    console.print(f"  entry size: {total} violation{'' if total == 1 else 's'}")
    for v in result["entry_size"]["violations"]:
        warning(
            f"{v['file']} {v['container']}[{v['key']}]: {v['length']} chars, cap {v['cap']} (over by {v['over_by']})"
        )
    console.print()
