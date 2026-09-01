# =================== AIPass ====================
# Name: log_watcher_service.py
# Description: Persistent log watcher process for Medic error detection
# Version: 1.2.0
# Created: 2026-03-29
# Modified: 2026-08-31
# =============================================

"""
Log Watcher Service — Persistent process for Medic

Starts both branch log watcher and system log watcher,
then blocks until SIGTERM/SIGINT. Designed to run as a
systemd user service (trigger-log-watcher.service).

Usage:
    python -m aipass.trigger.apps.log_watcher_service
    # Or via systemd: systemctl --user start trigger-log-watcher.service
"""

import os
import signal
import sys
import threading

import aipass.trigger.apps.handlers.reload_sentinel as reload_sentinel
from aipass.prax.apps.modules.logger import system_logger as logger
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


def print_introspection():
    """Display module introspection info."""
    try:
        from aipass.cli.apps.modules.display import console
    # OSError too: an uncured peer's import guard raises FileNotFoundError (@prax's rule, 2026-08-31).
    except (ImportError, OSError):
        logger.info("CLI console not available, using rich fallback")
        from rich.console import Console

        console = Console()

    console.print()
    console.print("[bold cyan]log_watcher_service Module[/bold cyan]")
    console.print("[dim]Persistent log watcher process — starts branch and system watchers as systemd service[/dim]")
    console.print()


# LIFECYCLE OUTPUT GOES TO PRAX, NOT THE JOURNAL (2026-08-31)
#
# Five bare print() calls used to write this service's lifecycle to stdout and
# stderr, where systemd captured them into the journal. They are prax logger
# calls below. The standard's complaint was exact rather than stylistic: those
# lines were unstructured and invisible to monitoring, and prax IS this system's
# monitoring surface — so `drone @prax monitor` could not see the state of the
# process that feeds it.
#
# THE TRADE, stated rather than glossed: `journalctl --user -u
# trigger-log-watcher.service` no longer carries "Running (... watchers active)",
# "Received signal N", or "Stopped". systemd's own Started / Stopping / Stopped
# and exit-status lines remain, so the journal still answers "is the process up".
# It no longer answers "did the watchers actually come up" — that is
# `drone @trigger medic status`, which reads the service, and the prax log.
#
# The startup failure is the one message here that is NOT info: it is logged at
# ERROR so it reaches the registry, and the level is pinned by
# test_both_fail_is_reported_at_error_level.
#
# The `--version` print at the bottom stays: it sits inside
# `if __name__ == "__main__"`, which the standard excludes, and a version query
# answering on stdout is what a caller parsing it expects.
def main() -> None:
    """Start watchers and block until signaled."""
    stop_event = threading.Event()

    def shutdown(signum: int, _frame: object) -> None:
        """Handle SIGTERM/SIGINT gracefully."""
        logger.info(f"[trigger-log-watcher] Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start both watchers
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

    # Watch our OWN handler code for changes. This process holds those modules
    # in memory for its whole life, so a fix shipped to disk does nothing until
    # it restarts — a gap that twice left this branch reporting a fix live while
    # the old code was still the one running. The sentinel sets the same
    # stop_event as a signal would, so the wait below is the only exit path.
    reload_requested = reload_sentinel.start(stop_event)

    # Block until shutdown signal
    stop_event.wait()

    # Graceful shutdown
    stop_branch_watcher()
    stop_system_watcher()

    if reload_requested():
        # NOT a clean exit on purpose: the unit ships Restart=on-failure, which
        # would read 0 as "job done" and leave the watcher down.
        logger.info(
            f"[trigger-log-watcher] Handler code changed — exiting {reload_sentinel.RELOAD_EXIT_CODE} to reload"
        )
        sys.exit(reload_sentinel.RELOAD_EXIT_CODE)

    logger.info("[trigger-log-watcher] Stopped")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--version", "-V"):
        print("log_watcher_service 1.0.0")
        sys.exit(0)
    main()
