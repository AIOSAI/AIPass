# =================== AIPass ====================
# Name: governance.py
# Description: Surfacing governance module — public API
# Version: 1.1.0
# Created: 2026-07-16
# Modified: 2026-07-16
# =============================================

"""
Surfacing Governance Module — Public API

Thin module re-exporting governance engine from handlers/governance/engine.py.
Cross-branch consumers import from here:

    from aipass.memory.apps.modules.governance import should_surface, record_message, new_state
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
from aipass.memory.apps.handlers.governance.engine import (
    DEFAULT_CONFIG,
    new_state,
    record_message,
    should_surface,
)

__all__ = ["should_surface", "record_message", "new_state", "DEFAULT_CONFIG"]


# =============================================================================
# MODULE ROUTING (handle_command for drone auto-discovery)
# =============================================================================


def print_introspection() -> None:
    """Display module introspection (seedgo standard)."""
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]governance Module[/bold cyan]")
    console.print("Pure surfacing governance — state-in/state-out decision functions")
    console.print()
    console.print("[yellow]Public API:[/yellow]")
    console.print("  should_surface(item_id, relevance_score, state, config)")
    console.print("  record_message(state)")
    console.print("  new_state()")
    console.print()
    console.print("[dim]Library module — import from: aipass.memory.apps.modules.governance[/dim]")


def handle_command(command: str, args: list) -> bool:
    """Entry point for drone module discovery — governance has no CLI surface."""
    if command != "governance":
        return False

    json_handler.log_operation("governance_command", {"args": args})

    if not args:
        print_introspection()
        return True

    if args[0] in ("--help", "-h", "help"):
        print_introspection()
        return True

    from aipass.cli.apps.modules import error

    error(f"governance: unknown subcommand '{args[0]}'")
    print_introspection()
    return True
