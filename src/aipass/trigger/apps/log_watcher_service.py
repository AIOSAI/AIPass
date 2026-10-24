# =================== AIPass ====================
# Name: log_watcher_service.py
# Description: Persistent log watcher process for Medic error detection
# Version: 1.5.0
# Created: 2026-03-29
# Modified: 2026-10-24
# =============================================

"""
Log Watcher Service — Persistent process for Medic"""

import os
import signal
import sys
import threading

import aipass.trigger.apps.handlers.reload_sentinel as reload_sentinel
from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.trigger.apps.modules.errors import purge_stale
from aipass.trigger.apps.modules.core import trigger
from aipass.trigger.apps.modules.medic import run_error_catchup
from aipass.trigger.apps.modules.branch_log_events import (
    start as start_branch_watcher,
    stop as stop_branch_watcher,
)
from aipass.trigger.apps.modules.log_events import (
    start as start_system_watcher,
    stop as stop_system_watcher,
)

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


def _console():
    """Return the shared CLI console, or a plain rich Console when cli is absent."""
    try:
        from aipass.cli.apps.modules.display import console
    # OSError too: an uncured peer's import guard raises FileNotFoundError.
    except (ImportError, OSError):
        logger.info("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()
    return console


def print_introspection():
    """Display module introspection info."""
    console = _console()
    console.print()
    console.print("[bold cyan]log_watcher_service Module[/bold cyan]")
    console.print("[dim]Persistent log watcher process — starts branch and system watchers as systemd service[/dim]")
    console.print("Run with --help for usage.")
    console.print()


def print_help():
    """Display usage. The service takes no subcommands: it runs until signalled."""
    console = _console()
    console.print()
    console.print("[bold cyan]Usage[/bold cyan]")
    console.print("  log_watcher_service              start the watchers and run until SIGTERM (the systemd unit)")
    console.print("  log_watcher_service --help, -h   this text; starts nothing")
    console.print("  log_watcher_service --version, -V")
    console.print()
    console.print("[bold cyan]Examples[/bold cyan]")
    console.print("  systemctl --user start trigger-log-watcher.service")
    console.print("  drone @trigger medic status")
    console.print()


# Lifecycle goes to the prax logger, not the journal; the startup failure is
# ERROR so it reaches the registry (pinned by test_both_fail_is_reported_at_error_level).
def main(argv: list[str] | None = None) -> None:
    """Start watchers and block until signaled.

    A help flag anywhere in argv prints usage and returns before anything starts."""
    if any(flag in ("--help", "-h") for flag in argv or []):
        print_help()
        return

    stop_event = threading.Event()

    def shutdown(signum: int, _frame: object) -> None:
        """Handle SIGTERM/SIGINT gracefully."""
        logger.info(f"[trigger-log-watcher] Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    branch_ok = start_branch_watcher()
    system_ok = start_system_watcher()

    if not branch_ok and not system_ok:
        logger.error("[trigger-log-watcher] Both watchers failed to start")
        sys.exit(1)

    started = []
    if branch_ok:
        started.append("branch")
    if system_ok:
        started.append("system")
    logger.info(f"[trigger-log-watcher] Running ({', '.join(started)} watchers active)")

    # The daemon restarts on every reload, so a start-up purge keeps the registry bounded.
    # Suppressed rows stay: a dropped one would dispatch again on its next recurrence.
    if purge_stale(30, keep_suppressed=True) < 0:
        logger.error("[trigger-log-watcher] Start-up registry purge failed")

    # Catch-up runs here, AFTER the watchers are up: overlap is safe (the registry
    # dedupes on fingerprint), a gap between scan and first watch is not.
    try:
        run_error_catchup(trigger.fire)
        logger.info("[trigger-log-watcher] Startup error catch-up complete")
    except Exception as exc:  # recovery must never stop the watchers
        logger.error(f"[trigger-log-watcher] Startup error catch-up failed: {exc}")

    # The sentinel sets the same stop_event as a signal, so the wait is the only exit path.
    reload_requested = reload_sentinel.start(stop_event)

    stop_event.wait()

    stop_branch_watcher()
    stop_system_watcher()

    if reload_requested():
        logger.info(
            f"[trigger-log-watcher] Handler code changed — exiting {reload_sentinel.RELOAD_EXIT_CODE} to reload"
        )
        sys.exit(reload_sentinel.RELOAD_EXIT_CODE)

    logger.info("[trigger-log-watcher] Stopped")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        print("log_watcher_service 1.0.0")
        sys.exit(0)
    main(sys.argv[1:])
