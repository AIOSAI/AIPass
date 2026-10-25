# =================== AIPass ====================
# Name: register.py
# Description: Dispatch Register
# Version: 1.4.0
# Created: 2026-08-22
# Modified: 2026-10-25
# =============================================

"""The dispatch register — what was promised, written before anything spawns.

Append-only: a dispatch is closed by a second record with the same id, never a rewrite.
Reference: docs/dispatch_register_and_feed.md
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.notify import append_jsonl, jsonl_records
from aipass.ai_mail.apps.handlers.paths import find_repo_root

REGISTER_FILENAME = "dispatch_register.jsonl"
REGISTER_LOCK_NAME = ".dispatch_register.lock"

# Larger than the feed's ceiling: an open entry must survive until its completion joins it.
REGISTER_MAX_LINES = 2000
REGISTER_KEEP_LINES = 1000

# Written at send; any other status closes the dispatch.
STATUS_OUTSTANDING = "outstanding"

# Distinct from the monitor's status: "the agent said done" is not "the monitor saw the exit".
STATUS_REPLIED = "completed (replied)"

# Absent on old rows and on the systemd-scope path; monitor_alive reads that as None, not dead.
MONITOR_PID_KEY = "monitor_pid"

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87


def _kernel32():
    """The Win32 kernel handle with its signatures set.

    Separate so a test can fake it: a fake object's bound methods cannot carry ``argtypes``.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _last_win32_error() -> int:
    """The error the last Win32 call left, read the way ctypes recommends."""
    import ctypes

    return ctypes.get_last_error()  # type: ignore[attr-defined]


def _monitor_alive_windows(pid: int) -> Optional[bool]:
    """The Windows leg of ``monitor_alive``: OpenProcess, never a signal.

    os.kill(pid, 0) on Windows is TerminateProcess. Access denied means the process exists.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        err = _last_win32_error()
        if err == _ERROR_INVALID_PARAMETER:
            return False
        if err == _ERROR_ACCESS_DENIED:
            return True
        logger.warning("[register] could not probe monitor pid %s: win32 error %s", pid, err)
        return None
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.pointer(exit_code)):
            logger.warning(
                "[register] could not read monitor pid %s exit state: win32 error %s", pid, _last_win32_error()
            )
            return None
        return exit_code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def monitor_alive(pid: Optional[int]) -> Optional[bool]:
    """Whether the monitor process *pid* still exists. None when it cannot be told.

    Three answers: "no pid recorded" is None, never False, or every historic row would read dead.
    """
    if not isinstance(pid, int) or pid <= 0:
        return None

    if sys.platform.startswith("linux"):
        return Path("/proc", str(pid)).exists()

    if sys.platform == "win32":
        return _monitor_alive_windows(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        logger.warning("[register] could not probe monitor pid %s: %s", pid, exc)
        return None
    return True


def register_file(repo_root: Optional[Path] = None) -> Path:
    """Where this project's dispatch register lives.

    With ``repo_root`` the answer is always rooted there, never the live path.
    AIPASS_DISPATCH_REGISTER (read every call) names the file when no ``repo_root`` is given.
    """
    override = os.environ.get("AIPASS_DISPATCH_REGISTER")
    if override and repo_root is None:
        return Path(override)
    root = find_repo_root()
    resolved = root / ".aipass" / REGISTER_FILENAME
    if repo_root is None:
        return resolved

    return repo_root / resolved.relative_to(root)


def open_dispatch(
    sender: str,
    target: str,
    subject: str,
    expected_seconds: int,
    repo_root: Optional[Path] = None,
    wake_back: bool = True,
    provider: str = "claude",
) -> Optional[str]:
    """Record that a dispatch was promised, and return its id.

    Called BEFORE the spawn. expected_seconds must be the lane's HARD_TIMEOUT, so "past
    expected_by" means the monitor died. None means unrecorded; the caller must still dispatch.
    """
    json_handler.log_operation("register_open_dispatch", {"sender": sender, "target": target})

    dispatch_id = str(uuid.uuid4())
    now = datetime.now().astimezone()

    record: Dict[str, object] = {
        "dispatch_id": dispatch_id,
        "ts": now.isoformat(),
        "sender": str(sender),
        "target": str(target),
        "subject": str(subject),
        "expected_by": (now + timedelta(seconds=expected_seconds)).isoformat(),
        "status": STATUS_OUTSTANDING,
        "provider": str(provider),
    }
    if not wake_back:
        # A reader can then tell a declined wake-back from a lost one.
        record["wake_back"] = False

    if not _append(record, repo_root):
        logger.warning(
            "[register] could not record dispatch %s -> %s (%r) — dispatch proceeds UNREGISTERED, "
            "so its completion will not be attributable and it will not show as outstanding",
            sender,
            target,
            subject,
        )
        return None

    return dispatch_id


def record_monitor_pid(
    dispatch_id: str,
    monitor_pid: int,
    repo_root: Optional[Path] = None,
) -> bool:
    """Annotate an open dispatch with the pid of the monitor now running it.

    Appends a second ``outstanding`` record, never a rewrite. False is non-fatal: callers log and carry on.
    """
    if not dispatch_id or not isinstance(monitor_pid, int) or monitor_pid <= 0:
        logger.warning(
            "[register] refusing to record monitor pid %r for dispatch %r — need a positive pid and an id",
            monitor_pid,
            dispatch_id,
        )
        return False

    try:
        current = _find_open_record(dispatch_id, repo_root)
    except OSError as exc:
        logger.warning("[register] cannot read register to annotate dispatch %s: %s", dispatch_id, exc)
        return False

    if current is None:
        logger.warning(
            "[register] no open record for dispatch %s — monitor pid %s not recorded",
            dispatch_id,
            monitor_pid,
        )
        return False

    record = dict(current)
    record[MONITOR_PID_KEY] = monitor_pid
    record["status"] = STATUS_OUTSTANDING

    if not _append(record, repo_root):
        logger.warning(
            "[register] could not annotate dispatch %s with monitor pid %s — the row keeps "
            "expected_by as its only death signal",
            dispatch_id,
            monitor_pid,
        )
        return False

    return True


def thread_subject(subject: str) -> str:
    """A subject reduced to the thread it belongs to."""
    text = str(subject or "").strip()
    lowered = text.lower()
    while lowered.startswith("re:"):
        text = text[3:].strip()
        lowered = text.lower()
    return lowered


def close_on_reply(
    replier: str,
    recipient: str,
    subject: str,
    repo_root: Optional[Path] = None,
) -> Optional[str]:
    """Close an open dispatch because its TARGET replied ON ITS THREAD.

    Matched by thread, not dispatch stamp: a resumed agent replies under a new id, and an
    early report-first mail is not a completion. Raises OSError if the register is unreadable.
    """
    thread = thread_subject(subject)
    if not replier or not recipient or not thread:
        return None

    rows = outstanding(repo_root=repo_root)

    for row in reversed(rows):  # oldest first, or a re-sent dispatch leaves its first row open forever
        if str(row.get("target", "")) != str(replier):
            continue
        if str(row.get("sender", "")) != str(recipient):
            continue
        if thread_subject(row.get("subject", "")) != thread:
            continue

        dispatch_id = str(row.get("dispatch_id", ""))
        if dispatch_id and close_dispatch(dispatch_id, STATUS_REPLIED, repo_root=repo_root):
            return dispatch_id
        return None

    return None


def _find_open_record(dispatch_id: str, repo_root: Optional[Path]) -> Optional[Dict]:
    """The newest still-open record for *dispatch_id*, or None if it is not open."""
    found: Optional[Dict] = None
    for record in jsonl_records(register_file(repo_root), strict=True):
        if record.get("dispatch_id") != dispatch_id:
            continue
        found = record if record.get("status") == STATUS_OUTSTANDING else None
    return found


def close_dispatch(
    dispatch_id: str,
    status: str,
    report_path: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> bool:
    """Close an outstanding dispatch by APPENDING a second record."""
    json_handler.log_operation("register_close_dispatch", {"dispatch_id": str(dispatch_id), "status": str(status)})

    record = {
        "dispatch_id": str(dispatch_id),
        "ts": datetime.now().astimezone().isoformat(),
        "status": str(status),
    }
    if report_path:
        record["report_path"] = str(report_path)

    if not _append(record, repo_root):
        logger.warning(
            "[register] could not close dispatch %s (%s) — it will read as outstanding forever, "
            "which is a FALSE ALARM rather than a missed one",
            dispatch_id,
            status,
        )
        return False

    return True


def outstanding(repo_root: Optional[Path] = None, now: Optional[datetime] = None) -> List[Dict]:
    """Every dispatch still open, newest first, each tagged with whether it is overdue.

    Adds ``overdue`` and a ``monitor_alive`` tri-state (None is not a death). Raises OSError if unreadable.
    """
    moment = now or datetime.now().astimezone()
    open_entries: Dict[str, Dict] = {}

    # strict=True: [] would read as "all clear" when the truth is "cannot tell"; @devpulse pins it.
    for record in jsonl_records(register_file(repo_root), strict=True):
        key = record.get("dispatch_id")
        if not key:
            continue
        if record.get("status") == STATUS_OUTSTANDING:
            open_entries[key] = record
        else:
            open_entries.pop(key, None)

    result = []
    for entry in open_entries.values():
        entry = dict(entry)
        entry["overdue"] = _is_overdue(entry, moment)
        # Derived at read time, never stored: a stored liveness is stale the instant it is written.
        entry["monitor_alive"] = monitor_alive(entry.get(MONITOR_PID_KEY))
        result.append(entry)

    return sorted(result, key=lambda e: str(e.get("ts", "")), reverse=True)


def _is_overdue(entry: Dict, moment: datetime) -> bool:
    """Whether *entry* is past its expected_by, saying so when it cannot be told."""
    raw = entry.get("expected_by")
    if not raw:
        return False

    try:
        expected = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        logger.warning(
            "[register] unparseable expected_by %r on dispatch %s — not counted as overdue",
            raw,
            entry.get("dispatch_id"),
        )
        return False

    if expected.tzinfo is None and moment.tzinfo is not None:
        expected = expected.replace(tzinfo=moment.tzinfo)

    return moment > expected


def _append(record: Dict, repo_root: Optional[Path]) -> bool:
    """Append one record. register_file() cannot fail, so only the write can."""
    return append_jsonl(
        register_file(repo_root),
        record,
        lock_name=REGISTER_LOCK_NAME,
        max_lines=REGISTER_MAX_LINES,
        keep_lines=REGISTER_KEEP_LINES,
    )
