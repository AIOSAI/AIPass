# =================== AIPass ====================
# Name: health.py
# Description: Branch health module — public API (entry-count + entry-size)
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Branch Health Module — Public API

Wraps two existing read-only checks — entry-count (is a branch's
``.trinity`` file over its rollover trigger) and entry-size (are any
entries over their character cap) — into one public function.

Built for @daemon: ``apps/handlers/*`` files are HANDLERS, and seedgo
blocks handler-to-other-branch-handler imports outright, so a consumer
in another branch cannot reach ``apps/handlers/monitor/detector.py`` or
``apps/handlers/json/lint_handler.py`` directly. This module is the
public, cross-branch-importable surface that bridges to both:

    from aipass.memory.apps.modules.health import get_branch_health

Strictly **read-only** — never writes, modifies, truncates, or deletes
any file.

Severity is the caller's call, not this module's — ``get_branch_health``
only reports facts. Intended severities (as recorded for @daemon's own
consumption, documented here so every consumer applies them the same
way):

    - Entry-count ``should_rollover: True``  -> INFO / pending. Rollover
      being due is not a fault; it auto-fires at the next PreCompact.
      Never WARNING.
    - Entry-size violations (``total_violations > 0``) -> WARNING. A
      write got past the character-cap gate.
"""

import os
import sys

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

from aipass.prax import logger  # noqa: F401
from aipass.memory.apps.handlers.json import json_handler

# Handler import (same package family — json handlers)
from aipass.memory.apps.handlers.json.lint_handler import run_lint

# Cross-handler access for branch discovery + rollover check (module
# layer bridges handlers — established precedent, see apps/modules/lint.py)
from aipass.memory.apps.handlers.monitor.detector import (
    _get_memory_file_path,
    _read_registry,
    check_single_file,
)

__all__ = ["get_branch_health"]


# =============================================================================
# PUBLIC API
# =============================================================================


def get_branch_health(branch_name: str) -> dict:
    """Combine entry-count and entry-size checks for one branch.

    Read-only. Never writes, modifies, truncates, or deletes any file.

    Resolves ``branch_name`` case-insensitively against the registry
    (``_read_registry()``). For each of ``local`` and ``observations``:
    resolves the ``.trinity`` file path via ``_get_memory_file_path`` and,
    if it exists, runs ``check_single_file`` (entry-count / rollover-
    trigger check). A memory_type whose file does not exist is skipped
    gracefully — its entry in the result is ``None`` — rather than
    failing the whole call. Entry-size violations come from
    ``run_lint`` scoped to this one branch.

    Args:
        branch_name: Branch name to check, matched case-insensitively.

    Returns:
        On an unknown branch::

            {"success": False, "error": "Unknown branch: <branch_name>"}

        On success::

            {
                "success": True,
                "branch": <canonical registry name>,
                "entry_count": {
                    "local": {"should_rollover": bool, "current_lines": int, "reason": str} | None,
                    "observations": {"should_rollover": bool, "current_lines": int, "reason": str} | None,
                },
                "entry_size": {"violations": [...], "total_violations": int},
            }

        See the module docstring for the intended severity mapping a
        consumer should apply to ``should_rollover`` and to a non-empty
        ``violations`` list — this function itself assigns none.
    """
    branches = _read_registry()

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
            # File vanished between resolution and check, or unreadable —
            # skip gracefully rather than erroring the whole call.
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


# =============================================================================
# MODULE ROUTING (handle_command for drone auto-discovery)
# =============================================================================


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]health Module[/bold cyan]")
    console.print("Read-only branch health — entry-count (rollover) + entry-size (cap violations)")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  get_branch_health(branch_name)")
    console.print()
    console.print("[dim]Library module — import from: aipass.memory.apps.modules.health[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery — health has no CLI surface."""
    if command != "health":
        return False

    json_handler.log_operation("health_command", {"args": args})

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    from aipass.cli.apps.modules import warning

    warning(f"health: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
