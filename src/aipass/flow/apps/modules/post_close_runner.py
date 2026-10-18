# =================== AIPass ====================
# Name: post_close_runner.py
# Description: Background post-close processing
# Version: 1.3.1
# Created: 2026-02-14
# Modified: 2026-10-17
# =============================================

"""
Post-Close Background Runner

Runs @memory archival as a background process.
Called by close_plan.py via subprocess.Popen so the close command returns fast.

Uses a lock file to prevent concurrent execution - if another instance is
already running, this one exits silently (the running instance will pick up
all unprocessed plans since it scans ALL of them). A lock file that cannot be
created at all (still denied after lock_ops' retry budget) is not "already
running": it is logged as an error and the runner exits non-zero.

This script lives inside the flow branch so handler import guards allow it.
"""

import sys
import os

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


from aipass.cli.apps.modules import console, error, success, warning
from aipass.flow.apps.handlers.cli.arg_gate import UnknownArgument, refuse_extra
from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.mbank.process import process_closed_plans
from aipass.flow.apps.handlers.runner.lock_ops import acquire_lock, release_lock
from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[3]
FLOW_ROOT = _PKG_ROOT / "flow"
MODULE_NAME = "post_close_runner"
LOCK_FILE = FLOW_ROOT / ".post_close_runner.lock"


def handle_command(command: str, args: list) -> bool:
    """Handle commands routed by the entry point."""
    if command not in ("post", "post_close_runner"):
        return False

    if not args:
        print_introspection()
        return True

    # Help anywhere in args: post archives and vectorises, so a help probe must not reach it.
    if wants_help(args):
        print_help()
        return True

    try:
        refuse_extra(args, door="post")
    except UnknownArgument as exc:
        error(exc.message, suggestion=exc.usage)
        raise SystemExit(1) from exc

    json_handler.log_operation("post_close_processed", {"command": command, "args": args})

    try:
        acquired = acquire_lock(LOCK_FILE)
    except OSError as e:
        # A lock that cannot be created, read or removed is not a running instance.
        logger.error("[%s] Could not create lock %s: %s", MODULE_NAME, LOCK_FILE, e)
        error(f"Could not create lock: {e}")
        return True
    if not acquired:
        warning("Another instance is already running")
        return True

    try:
        process_closed_plans()

        try:
            import importlib

            _plans_mod = importlib.import_module("aipass.memory.apps.modules.door_plans_processor")
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


def main(argv: list[str]) -> int:
    """Run the pass close_plan starts as a detached program; answer its exit code.
    A function so tests can run it with LOCK_FILE redirected. 1 only when the lock cannot be created."""
    if "--help" in argv or "-h" in argv:
        print_help()
        return 0

    try:
        acquired = acquire_lock(LOCK_FILE)
    except OSError as e:
        logger.error("[%s] Could not create lock %s: %s", MODULE_NAME, LOCK_FILE, e)
        return 1
    if not acquired:
        return 0

    try:
        process_closed_plans()

        try:
            import importlib

            _plans_mod = importlib.import_module("aipass.memory.apps.modules.door_plans_processor")
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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
