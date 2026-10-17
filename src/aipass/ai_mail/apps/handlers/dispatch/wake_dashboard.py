# =================== AIPass ====================
# Name: wake_dashboard.py
# Description: Recipient dashboard refresh for the wake path
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""Refresh the recipient's dashboard on the way into a wake."""

import os
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


if TYPE_CHECKING:  # pragma: no cover — import-cycle-free typing only
    from aipass.ai_mail.apps.handlers.dispatch.wake import DispatchStatus


# Not a tuning knob: the promise that a refresh which never returns cannot make a dispatch late.
DASHBOARD_REFRESH_TIMEOUT = 5.0


def refresh_recipient_dashboard(branch_path: Path, email: str, status: "DispatchStatus") -> None:
    """Refresh the RECIPIENT's DASHBOARD.local.json before their session starts."""
    # Fail-open by contract: every failure is a WARNING, the spawn goes ahead, nothing raises.
    outcome: dict = {}

    def _run() -> None:
        try:
            # Local import: a broken prax dashboard must not be an ImportError that kills every wake.
            from aipass.prax.apps.modules.dashboard import refresh_single_dashboard

            outcome["result"] = refresh_single_dashboard(branch_path)
        except Exception as exc:  # every failure is the same fail-open
            # Logged here so the record exists even if the join times out and leaves this worker behind.
            logger.warning("[wake] dashboard refresh for %s failed: %s — spawning anyway", email, exc)
            outcome["error"] = exc

    started = time.monotonic()
    # A thread, not signal.alarm: that is POSIX- and main-thread-only, and this runs under the daemon.
    worker = threading.Thread(target=_run, name=f"wake-dashboard-{branch_path.name}", daemon=True)
    worker.start()
    worker.join(DASHBOARD_REFRESH_TIMEOUT)
    elapsed = time.monotonic() - started

    if worker.is_alive():
        detail = f"Refresh for {email} still running after {DASHBOARD_REFRESH_TIMEOUT:.1f}s — spawning anyway"
        logger.warning(
            "[wake] dashboard refresh for %s exceeded %.1fs — spawning anyway", email, DASHBOARD_REFRESH_TIMEOUT
        )
        status.warn("dashboard", detail)
        return

    error = outcome.get("error")
    if error is not None:
        detail = f"Refresh for {email} failed ({type(error).__name__}: {error}) — spawning anyway"
        status.warn("dashboard", detail)
        return

    result = outcome.get("result") or {}
    if result.get("status") != "success":
        # prax returns its failures rather than raising them; a non-"success" dict is a failure.
        reason = result.get("error", "no status returned")
        detail = f"Refresh for {email} reported {result.get('status')!r}: {reason} — spawning anyway"
        logger.warning("[wake] dashboard refresh for %s reported failure: %s", email, reason)
        status.warn("dashboard", detail)
        return

    logger.info("[wake] dashboard refreshed for %s in %.2fs", email, elapsed)
    status.ok("dashboard", f"Refreshed {email} in {elapsed:.2f}s")


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    json_handler.log_operation("wake_dashboard_introspection")
    console.print("\nWAKE DASHBOARD REFRESH")
    console.print(f"  bound: {DASHBOARD_REFRESH_TIMEOUT} s")
    console.print("  refresh_recipient_dashboard(branch_path, email, status) -> None")
    console.print()
