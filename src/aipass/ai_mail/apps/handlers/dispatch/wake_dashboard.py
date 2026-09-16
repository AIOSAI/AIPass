# =================== AIPass ====================
# Name: wake_dashboard.py
# Description: Recipient dashboard refresh for the wake path
# Version: 1.0.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""Refresh the recipient's dashboard on the way into a wake.

One concern, one file: ``wake.py`` reached seedgo's 1,500-line limit the moment
this landed inside it, and a bounded fail-open call to another branch's service
is a seam worth naming anyway. ``wake.py`` imports the function under its own
private alias, so every existing pin and stub keeps the name it always had.
"""

import os
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

# The console entry point below renders through Rich; a cp1252 terminal would
# raise on the arrows and box characters the fleet's output uses.
if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


if TYPE_CHECKING:  # pragma: no cover — import-cycle-free typing only
    from aipass.ai_mail.apps.handlers.dispatch.wake import DispatchStatus


# How long a wake will wait for the recipient's dashboard, in seconds.
#
# Measured by @devpulse on 2026-09-15 (FPLAN-0593): 0.85-0.98 s per branch,
# zero agent tokens. Five seconds is that cost with room for a cold cache and
# a busy disk, and still far under the time a spawn takes — but the bound is
# not a performance tuning knob, it is the promise that a refresh which never
# returns cannot become the reason a dispatch is late.
DASHBOARD_REFRESH_TIMEOUT = 5.0


def refresh_recipient_dashboard(branch_path: Path, email: str, status: "DispatchStatus") -> None:
    """Refresh the RECIPIENT's DASHBOARD.local.json before their session starts.

    An agent's first act on waking is to read its dashboard as its single
    status glance. Until now nothing refreshed it on the way in, so the woken
    agent read whatever its own last session left behind — a dashboard saying
    "0 unread" while the dispatch that woke it sat in the inbox. The cheapest
    place to fix that is here, in the hand-over: the wake already knows exactly
    which branch is about to start.

    ONE BRANCH, NEVER THE FLEET. ``refresh_all_dashboards`` walks 18 branches;
    the recipient is one of them and the other 17 are nobody's business on this
    code path. Measured 0.85-0.98 s for the single branch, zero agent tokens.

    FAIL-OPEN, AND THAT IS THE ONE EXEMPTION FROM FAILING HONESTLY IN THIS
    FILE. A stale dashboard costs a woken agent one refresh of its own; a wake
    that dies costs the dispatch entirely. So every failure — an import that
    cannot resolve, a raise, an error status prax returned rather than raised,
    or a refresh still running when the bound expires — is recorded as a
    WARNING naming the branch and the spawn goes ahead. Nothing here returns a
    value or raises: the caller cannot be given a way to abort on this.

    The import is deliberately LOCAL, and through prax's MODULE door rather than
    its handler: the module is the published surface another branch is allowed
    to read. Local because a module-level import would make a broken prax
    dashboard an ImportError at ai_mail import time — every wake dead for a
    dashboard, which is exactly the trade this function exists to refuse.

    The bound needs a thread because the work is an ordinary blocking call:
    ``signal.alarm`` is POSIX-only and main-thread-only, and this runs under the
    daemon as often as under a terminal. The worker is a daemon thread, so an
    overrun cannot hold the process open either.
    """
    outcome: dict = {}

    def _run() -> None:
        try:
            from aipass.prax.apps.modules.dashboard import refresh_single_dashboard

            outcome["result"] = refresh_single_dashboard(branch_path)
        except Exception as exc:  # noqa: BLE001 — every failure is the same fail-open
            # Logged HERE, in the thread that saw it, so the record exists even
            # if the join below times out first and this worker is left behind.
            logger.warning("[wake] dashboard refresh for %s failed: %s — spawning anyway", email, exc)
            outcome["error"] = exc

    started = time.monotonic()
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
        # Already logged inside the worker; this is the caller's own verdict.
        detail = f"Refresh for {email} failed ({type(error).__name__}: {error}) — spawning anyway"
        status.warn("dashboard", detail)
        return

    result = outcome.get("result") or {}
    if result.get("status") != "success":
        # prax catches its own exceptions and RETURNS the failure, so a dict
        # that is not "success" is the same event as a raise — read it, never
        # assume the call that came back did the work.
        reason = result.get("error", "no status returned")
        detail = f"Refresh for {email} reported {result.get('status')!r}: {reason} — spawning anyway"
        logger.warning("[wake] dashboard refresh for %s reported failure: %s", email, reason)
        status.warn("dashboard", detail)
        return

    # INFO on the way through: the wall time is the number this build is judged
    # on, and after the fact the log is the only place left holding it.
    logger.info("[wake] dashboard refreshed for %s in %.2fs", email, elapsed)
    status.ok("dashboard", f"Refreshed {email} in {elapsed:.2f}s")


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    json_handler.log_operation("wake_dashboard_introspection")
    console.print("\nWAKE DASHBOARD REFRESH")
    console.print(f"  bound: {DASHBOARD_REFRESH_TIMEOUT} s")
    console.print("  refresh_recipient_dashboard(branch_path, email, status) -> None")
    console.print()
