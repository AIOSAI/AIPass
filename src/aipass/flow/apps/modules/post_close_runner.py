# =================== AIPass ====================
# Name: post_close_runner.py
# Description: Background post-close processing
# Version: 1.4.1
# Created: 2026-02-14
# Modified: 2026-11-26
# =============================================

"""
Post-Close Background Runner

Runs @memory archival as a background process.
Called by close_plan.py via subprocess.Popen so the close command returns fast.

A held lock means a running instance: this one leaves a rerun marker for that
holder and exits 0; a lock or marker that cannot be created is logged and exits 1.

This script lives inside the flow branch so handler import guards allow it.
"""

import sys
from pathlib import Path


from aipass.cli import console, error
from aipass.flow.apps.handlers.cli.arg_gate import UnknownArgument, refuse_extra
from aipass.flow.apps.handlers.cli.help_flags import wants_help
from aipass.flow.apps.handlers.json import json_handler
from aipass.flow.apps.handlers.mbank.process import process_closed_plans
from aipass.flow.apps.handlers.runner.lock_ops import acquire_lock, release_lock
from aipass.prax import logger

_PKG_ROOT = Path(__file__).resolve().parents[3]
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
    console.print("[yellow]EXAMPLES:[/yellow]")
    console.print("  [dim]drone @flow post[/dim]          # Show connected handlers")
    console.print("  [dim]drone @flow post --help[/dim]   # This help")
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

    # Marker before lock: the holder re-runs while it exists, so a close landing after its listing still drains.
    rerun = LOCK_FILE.with_name(LOCK_FILE.name + ".rerun")
    try:
        rerun.touch()
    except OSError as e:
        logger.error("[%s] Could not leave rerun marker %s: %s", MODULE_NAME, rerun, e)
        return 1
    while rerun.exists():
        try:
            acquired = acquire_lock(LOCK_FILE)
        except OSError as e:
            logger.error("[%s] Could not create lock %s: %s", MODULE_NAME, LOCK_FILE, e)
            return 1
        if not acquired:
            logger.info("[%s] Lock held, rerun marker left for its holder: %s", MODULE_NAME, rerun)
            return 0
        try:
            release_lock(rerun)
            _run_pass(argv)
        finally:
            release_lock(LOCK_FILE)
    return 0


def _run_pass(argv: list[str]) -> None:
    """One archive and vectorize pass over every closed plan; a failure is logged and the next pass still runs."""
    json_handler.log_operation("post_close_processed", {"argv": argv[1:]})
    try:
        process_closed_plans()

        try:
            from aipass.memory import process_plans

            result = process_plans()
            if result.get("success"):
                logger.info("[%s] Plan vectorization: %s", MODULE_NAME, result)
            else:
                logger.error("[%s] Plan vectorization failed: %s", MODULE_NAME, result.get("error", "unknown"))
        except Exception as e:
            logger.error("[%s] Plan vectorization error: %s", MODULE_NAME, e)

    except Exception as e:
        logger.error(f"[{MODULE_NAME}] Background processing failed: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
