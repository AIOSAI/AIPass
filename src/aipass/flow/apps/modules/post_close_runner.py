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

import os
import sys
from pathlib import Path

# INFRASTRUCTURE IMPORT PATTERN
_PKG_ROOT = Path(__file__).resolve().parents[3]  # file.py → modules/ → apps/ → flow/ → aipass/
FLOW_ROOT = _PKG_ROOT / "flow"

# External: CLI console (Rich display) and Prax logger
from aipass.cli.apps.modules import console, error, warning
from aipass.prax.apps.modules.logger import system_logger as logger

# JSON handler for operation tracking
from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "post_close_runner"

LOCK_FILE = FLOW_ROOT / ".post_close_runner.lock"

# AI summarization removed — plans vectorized directly from flow/processed_plans/
# from aipass.flow.apps.handlers.summary.generate import generate_summaries
from aipass.flow.apps.handlers.mbank.process import process_closed_plans


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

    # Handle help flag
    if args[0] in ["--help", "-h", "help"]:
        print_help()
        return True

    # Log the operation
    json_handler.log_operation("post_close_processed", {"command": command, "args": args})

    # Run the post-close processing directly (foreground)
    if not _acquire_lock():
        warning("Another instance is already running")
        return True

    try:
        process_closed_plans()
        console.print("[green]Processing complete[/green]")
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")
        error(f"Processing failed: {e}")
    finally:
        _release_lock()

    return True


def _try_create_lock() -> bool:
    """Atomically create lock file with current PID. Returns True on success."""
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        logger.info("[%s] Lock file already exists, cannot acquire", MODULE_NAME)
        return False


def _is_lock_stale() -> bool:
    """Check if existing lock file belongs to a dead process."""
    try:
        pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        logger.info("[%s] Another instance running (PID %d), exiting", MODULE_NAME, pid)
        return False  # Process alive — lock is valid
    except (ValueError, ProcessLookupError, PermissionError):
        logger.info("[%s] Stale lock found, taking over", MODULE_NAME)
        return True


def _acquire_lock() -> bool:
    """Try to acquire lock file. Returns True if acquired, False if another instance is running.

    Uses atomic O_CREAT | O_EXCL to avoid TOCTOU race between existence check and write.
    """
    if _try_create_lock():
        return True

    # Lock exists — check if stale
    if not _is_lock_stale():
        return False

    # Remove stale lock and retry
    try:
        LOCK_FILE.unlink()
    except OSError as exc:
        logger.warning("[%s] Failed to remove stale lock: %s", MODULE_NAME, exc)
        return False

    if not _try_create_lock():
        logger.info("[%s] Another process grabbed lock during retry", MODULE_NAME)
        return False

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

    if not _acquire_lock():
        sys.exit(0)

    try:
        # generate_summaries() — removed, AI summarization no longer needed
        process_closed_plans()
    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")
    finally:
        _release_lock()
