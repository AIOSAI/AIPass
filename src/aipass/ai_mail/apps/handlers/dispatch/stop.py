# =================== AIPass ====================
# Name: stop.py
# Description: End a running dispatch from outside: the stop verb's handler, and the live-monitor test close uses
# Version: 1.0.1
# Created: 2026-11-01
# Modified: 2026-11-02
# =============================================

"""
End a running dispatch from outside.

The monitor's process group is ended (TERM, a grace, then KILL) before its retries, bounce
and wake-back can run, so the stop reads as stopped, not failed. The register row is closed
as stopped and the dispatcher is mailed. The session pointer and transcript are never
touched, so a later resume in the branch continues where the agent stopped.
"""

import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.dispatch import register
from aipass.ai_mail.apps.handlers.dispatch.pid_lock import check_lock, check_pid_alive
from aipass.ai_mail.apps.handlers.email.delivery import deliver_email_to_branch

STATUS_STOPPED = "stopped"
GRACE_SECONDS = 5.0
MONITOR_MARK = "dispatch_monitor"


def is_monitor(pid: int) -> bool:
    """Whether pid runs the dispatch monitor: a lock's pid may be a pre-spawn parent or a reused number."""
    if sys.platform == "win32":
        # shortcut: Windows has no ps; the lock's live pid is trusted. Upgrade with a WMI query if Windows dispatches.
        return True
    try:
        result = subprocess.run(["ps", "-ww", "-o", "args=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("[stop] cannot read the command line of PID %s: %s", pid, e)
        return False
    found = MONITOR_MARK in result.stdout
    if not found:
        logger.info(
            "[stop] PID %s is not a dispatch monitor (ps exit %s): %r", pid, result.returncode, result.stdout[:200]
        )
    return found


def _alive(pid: int, as_group: bool) -> bool:
    if not as_group:
        return check_pid_alive(pid)
    try:
        os.killpg(pid, 0)
    except OSError:
        return False
    return True


def _signal(pid: int, as_group: bool, sig: int) -> None:
    try:
        if as_group:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)
    except OSError as e:
        logger.info("[stop] signal %s to PID %s not sent, already gone: %s", sig, pid, e)


def _end_process_group(pid: int, grace: float) -> None:
    """TERM the monitor's group (the monitor and its agent), wait out the grace, then KILL what is left."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True, timeout=15)
        deadline = time.monotonic() + grace
        while check_pid_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
        return
    # Both spawn lanes make the monitor a session leader; anything else gets the pid alone, never a stranger's group.
    try:
        as_group = os.getpgid(pid) == pid
    except OSError as e:
        logger.info("[stop] PID %s gone before the stop: %s", pid, e)
        return
    _signal(pid, as_group, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while _alive(pid, as_group) and time.monotonic() < deadline:
        time.sleep(0.2)
    if _alive(pid, as_group):
        logger.warning("[stop] PID %s outlived %.0fs of SIGTERM — sending SIGKILL", pid, grace)
        _signal(pid, as_group, signal.SIGKILL)


def _mail_dispatcher(entry: dict, email: str, by: str, when: str) -> Tuple[bool, str]:
    sender = str(entry.get("sender") or "")
    email_data = {
        "from": "@ai_mail",
        "from_name": "AI_MAIL",
        "to": sender,
        "subject": f"Dispatch stopped: {email} (by {by})",
        "message": (
            f"{by} stopped {email}'s dispatch {entry.get('dispatch_id')} at {when}.\n"
            f"Subject: {entry.get('subject') or '(no subject)'}\n\n"
            f"Stopped, not failed: no wake-back follows and nothing should retry it.\n"
            f"The session pointer is kept, so a resume in {email}'s branch continues where it stopped."
        ),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "auto_execute": False,
        "priority": "normal",
        "reply_to": "@ai_mail",
    }
    return deliver_email_to_branch(sender, email_data)


def running_monitor(branch_path: Path) -> Optional[int]:
    """The pid of the live dispatch monitor holding the branch's lock, or None when none runs."""
    lock = check_lock(branch_path)
    pid = lock.get("pid") if lock else None
    return pid if isinstance(pid, int) and is_monitor(pid) else None


def stop_dispatch(branch_path: Path, email: str, by: str) -> Tuple[bool, str, str]:
    """(stopped, the one output line, a warning or "").

    False with "no dispatch is running for @x" when no live monitor holds the branch's lock.
    """
    json_handler.log_operation("dispatch_stop", {"target": email, "by": by})
    pid = running_monitor(branch_path)
    if pid is None:
        return False, f"no dispatch is running for {email}", ""

    try:
        entry: Optional[dict] = next((e for e in register.outstanding() if e.get("target") == email), None)
    except OSError as e:
        logger.warning("[stop] register unreadable, stopping %s unregistered: %s", email, e)
        entry = None

    _end_process_group(pid, GRACE_SECONDS)
    if check_pid_alive(pid):
        return False, f"{email}'s monitor (PID {pid}) is still running after SIGKILL", ""
    check_lock(branch_path)
    when = datetime.now().astimezone().isoformat(timespec="seconds")
    logger.info("[stop] %s stopped by %s (monitor PID %s)", email, by, pid)

    if entry is None:
        return True, f"stopped {email} (dispatch unregistered, by {by})", "no register row, so no dispatcher was mailed"

    dispatch_id = str(entry.get("dispatch_id"))
    notes = []
    if not register.close_dispatch(dispatch_id, STATUS_STOPPED):
        notes.append("the register row could not be closed")
    delivered, reason = _mail_dispatcher(entry, email, by, when)
    if not delivered:
        logger.warning("[stop] stop mail to %s not delivered: %s", entry.get("sender"), reason)
        notes.append(f"the mail to {entry.get('sender')} was not delivered ({reason})")
    return True, f"stopped {email} (dispatch {dispatch_id}, by {by})", "; ".join(notes)
