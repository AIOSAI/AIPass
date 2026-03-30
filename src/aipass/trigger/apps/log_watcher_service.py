# =================== AIPass ====================
# Name: log_watcher_service.py
# Description: Persistent log watcher process for Medic error detection
# Version: 1.0.0
# Created: 2026-03-29
# Modified: 2026-03-29
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

import signal
import sys
import threading

from aipass.trigger.apps.modules.branch_log_events import (
    start as start_branch_watcher,
    stop as stop_branch_watcher,
)
from aipass.trigger.apps.modules.log_events import (
    start as start_system_watcher,
    stop as stop_system_watcher,
)


def print_introspection():
    """Display module introspection info."""
    print()
    print("log_watcher_service Module")
    print("Persistent log watcher process — starts branch and system watchers as systemd service")
    print()


def main() -> None:
    """Start watchers and block until signaled."""
    stop_event = threading.Event()

    def shutdown(signum: int, _frame: object) -> None:
        """Handle SIGTERM/SIGINT gracefully."""
        print(f"[trigger-log-watcher] Received signal {signum}, shutting down...")
        stop_event.set()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    # Start both watchers
    branch_ok = start_branch_watcher()
    system_ok = start_system_watcher()

    if not branch_ok and not system_ok:
        print("[trigger-log-watcher] Both watchers failed to start", file=sys.stderr)
        sys.exit(1)

    started = []
    if branch_ok:
        started.append("branch")
    if system_ok:
        started.append("system")
    print(f"[trigger-log-watcher] Running ({', '.join(started)} watchers active)")

    # Block until shutdown signal
    stop_event.wait()

    # Graceful shutdown
    stop_branch_watcher()
    stop_system_watcher()
    print("[trigger-log-watcher] Stopped")


if __name__ == "__main__":
    main()
