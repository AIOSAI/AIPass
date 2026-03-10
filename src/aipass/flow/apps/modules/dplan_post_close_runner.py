# =================== AIPass ====================
# Name: dplan_post_close_runner.py
# Description: Background post-close processing for DPLANs
# Version: 1.1.0
# Created: 2026-02-18
# Modified: 2026-02-18
# =============================================

"""
Post-Close Background Runner for DPLANs

Runs Memory Bank archival as a background process.
Called by dev_flow.py via subprocess.Popen so the close command returns fast.

Uses a lock file to prevent concurrent execution - if another instance is
already running, this one exits silently.
"""

import os
import sys
from pathlib import Path

# INFRASTRUCTURE IMPORT PATTERN
# dplan_post_close_runner.py → modules/ → apps/ → flow/
FLOW_ROOT = Path(__file__).resolve().parents[2]

# External: CLI console (Rich display) and Prax logger
from aipass.cli.apps.modules import console
from aipass.prax.apps.modules.logger import system_logger as logger

MODULE_NAME = "dplan_post_close_runner"

LOCK_FILE = FLOW_ROOT / ".post_close_runner.lock"

from aipass.flow.apps.handlers.mbank.process import process_closed_plans


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point.

    This module is a background utility runner, not a user-facing command.
    It responds to 'dplan_post_close' for drone routing compatibility
    and supports --help / -h for introspection.

    Args:
        command: Command name
        args: Command arguments

    Returns:
        True if command was handled, False otherwise
    """
    if command != "dplan_post_close":
        return False

    if args and args[0] in ("--help", "-h"):
        print_help()
        return True

    # Run the post-close processing directly (foreground)
    if not _acquire_lock():
        console.print("[yellow]Another instance is already running[/yellow]")
        return True

    try:
        result = process_closed_plans()
        console.print(f"[green]Processing complete:[/green] {result.get('processed', 0)} processed, {result.get('errors', 0)} errors")
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")
        console.print(f"[red]Processing failed: {e}[/red]")
    finally:
        _release_lock()

    return True


def _acquire_lock() -> bool:
    """Try to acquire lock file. Returns True if acquired, False if another instance is running."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            os.kill(pid, 0)  # Signal 0 = check if process exists
            logger.info(f"[{MODULE_NAME}] Another instance running (PID {pid}), exiting")
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            logger.info(f"[{MODULE_NAME}] Stale lock found, taking over")

    LOCK_FILE.write_text(str(os.getpid()))
    return True


def _release_lock():
    """Release the lock file."""
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"[{MODULE_NAME}] Failed to release lock file: {e}")


def print_introspection():
    """Display module introspection info."""
    console.print()
    console.print("dplan_post_close_runner Module")
    console.print("Background post-close processing for DPLANs — runs Memory Bank archival")
    console.print()
    console.print("Connected Handlers:")
    console.print("  handlers/mbank/  (local)")
    console.print("    - process.py (process_closed_plans — scan and archive closed plans)")
    console.print()


def print_help():
    """Display help for this background runner."""
    console.print(f"Usage: python {Path(__file__).name}")
    console.print()
    console.print("Post-Close Background Runner for DPLANs")
    console.print("Runs Memory Bank archival as a background process.")
    console.print("Called by dev_flow.py via subprocess — not intended for direct use.")
    console.print()
    console.print("Options:")
    console.print("  -h, --help    Show this help message")


if __name__ == "__main__":
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        sys.exit(0)

    if not _acquire_lock():
        sys.exit(0)

    try:
        result = process_closed_plans()
        logger.info(f"[{MODULE_NAME}] Processing complete: {result.get('processed', 0)} processed, {result.get('errors', 0)} errors")
        for entry in result.get("results", []):
            status = entry.get("status", "unknown")
            plan = entry.get("plan", "?")
            if "error" in status or "stranded" in status:
                logger.warning(f"[{MODULE_NAME}] {plan}: {status} — {entry.get('error', 'no detail')}")
            else:
                logger.info(f"[{MODULE_NAME}] {plan}: {status}")
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")
    finally:
        _release_lock()
