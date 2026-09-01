# =================== AIPass ====================
# Name: central.py
# Description: Central File Push Module
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-07
# =============================================

"""
Central File Push Module

Thin router for the push-central command. Delegates to
handlers/central/central_writer.py to aggregate commons stats
and write COMMONS.central.json.

Handles: push-central command.
"""

from typing import List

from aipass.prax.apps.modules.logger import system_logger as logger

try:
    from aipass.cli.apps.modules import console, error, success
except (ImportError, OSError):
    logger.warning("[central] CLI console unavailable, using fallback")
    from rich.console import Console

    console = Console()
    error = console.print  # type: ignore[assignment]
    success = console.print  # type: ignore[assignment]

from aipass.commons.apps.handlers.central.central_writer import update_central
from aipass.commons.apps.handlers.json import json_handler


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("central")
    console.print(
        "Thin router for the push-central command — aggregates commons stats and writes COMMONS.central.json."
    )
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/central/")
    console.print("    - central_writer.py (update_central — aggregate stats and write central file)")
    console.print()


# =============================================================================
# COMMAND ROUTING
# =============================================================================


def handle_command(command: str, args: List[str]) -> bool:
    """
    Handle central file push commands.

    Args:
        command: Command name (push-central)
        args: Command arguments

    Returns:
        True if command handled, False otherwise
    """
    if command != "push-central":
        return False

    if "--dry-run" in args:
        console.print()
        console.print("[bold cyan][DRY RUN] Would aggregate branch stats and write COMMONS.central.json[/bold cyan]")
        console.print()
        return True

    try:
        stats = update_central()
        branch_count = len(stats.get("branch_stats", {}))
        success(f"Central file updated: {branch_count} branches")
        json_handler.log_operation("push-central_executed", {"command": "push-central", "success": True})
        return True
    except Exception as e:
        logger.error(f"[commons] push-central failed: {e}")
        error(f"Error: {e}")
        return True
