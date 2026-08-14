# =================== AIPass ====================
# Name: post_close_runner.py
# Description: Background post-close processing
# Version: 1.2.0
# Created: 2026-02-14
# Modified: 2026-02-14
# =============================================

"""
Post-Close Background Runner

Runs @memory archival as a background process.
Called by close_plan.py via subprocess.Popen so the close command returns fast.

Uses a lock file to prevent concurrent execution - if another instance is
already running, this one exits silently (the running instance will pick up
all unprocessed plans since it scans ALL of them).

This script lives inside the flow branch so handler import guards allow it.
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

from aipass.cli.apps.modules import console, error, success, warning
from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.mbank.process import process_closed_plans
from aipass.flow.apps.handlers.runner.lock_ops import acquire_lock, release_lock
from aipass.prax.apps.modules.logger import system_logger as logger

_PKG_ROOT = Path(__file__).resolve().parents[3]
FLOW_ROOT = _PKG_ROOT / "flow"
MODULE_NAME = "post_close_runner"
LOCK_FILE = FLOW_ROOT / ".post_close_runner.lock"


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    This module is a background utility runner, not a user-facing command.
    It responds to 'post_close' for drone routing compatibility
    and supports --help / -h for introspection.

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    if command not in ("post", "post_close_runner"):
        return False

    if not args:
        print_introspection()
        return True

    # Handle help flag ANYWHERE in the sequence -- post archives and
    # vectorises closed plans, so a help probe must not reach it
    if wants_help(args):
        print_help()
        return True

    # Log the operation
    json_handler.log_operation("post_close_processed", {"command": command, "args": args})

    # Run the post-close processing directly (foreground)
    if not acquire_lock(LOCK_FILE):
        warning("Another instance is already running")
        return True

    try:
        process_closed_plans()

        try:
            import importlib

            _plans_mod = importlib.import_module("aipass.memory.apps.handlers.intake.plans_processor")
            result = _plans_mod.process_plans()
            if result.get("success"):
                count = result.get("files_processed", 0)
                chunks = result.get("total_chunks", 0)
                if count > 0:
                    success(f"Vectorized {count} plan(s) ({chunks} chunks)")
                logger.info("[%s] Plan vectorization: %s", MODULE_NAME, result)
            else:
                logger.error("[%s] Plan vectorization failed: %s", MODULE_NAME, result.get("error", "unknown"))
                error(f"Vectorization failed: {result.get('error', 'unknown')}")
        except Exception as e:
            logger.error("[%s] Plan vectorization error: %s", MODULE_NAME, e)
            error(f"Vectorization error: {e}")

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")
        error(f"Processing failed: {e}")
    finally:
        release_lock(LOCK_FILE)

    return True


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("[bold cyan]post_close_runner Module[/bold cyan]")
    console.print()

    console.print("[yellow]Connected Handlers:[/yellow]")
    console.print()
    console.print("  [cyan]handlers/mbank/[/cyan]")
    console.print("    [dim]- process.py (process_closed_plans — scan and archive closed plans)[/dim]")
    console.print()

    console.print("[dim]Run 'drone @flow post --help' for usage[/dim]")
    console.print()


def print_help():
    """Print help information for post_close_runner module"""
    console.print()
    console.print("[bold cyan]post_close_runner[/bold cyan] — Background post-close processing")
    console.print()
    console.print("[yellow]USAGE:[/yellow]")
    console.print("  drone @flow post")
    console.print()
    console.print("[yellow]NOTES:[/yellow]")
    console.print("  Background utility — called by close_plan.py via subprocess.")
    console.print("  Not typically invoked directly.")
    console.print()


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print_help()
        sys.exit(0)

    if not acquire_lock(LOCK_FILE):
        sys.exit(0)

    try:
        process_closed_plans()

        try:
            import importlib

            _plans_mod = importlib.import_module("aipass.memory.apps.handlers.intake.plans_processor")
            result = _plans_mod.process_plans()
            if result.get("success"):
                logger.info("[%s] Plan vectorization: %s", MODULE_NAME, result)
            else:
                logger.error("[%s] Plan vectorization failed: %s", MODULE_NAME, result.get("error", "unknown"))
        except Exception as e:
            logger.error("[%s] Plan vectorization error: %s", MODULE_NAME, e)

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")
    finally:
        release_lock(LOCK_FILE)
