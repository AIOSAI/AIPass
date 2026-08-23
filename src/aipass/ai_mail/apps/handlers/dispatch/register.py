# =================== AIPass ====================
# Name: register.py
# Description: Dispatch Register
# Version: 1.0.0
# Created: 2026-08-22
# Modified: 2026-08-22
# =============================================

"""The dispatch register — what was promised, written before anything spawns.

v1.0.0 — FPLAN-0452 P0

Patrick's rule 1 (DPLAN-0317): *"Any dispatch of any agent — inside AIPass or
external, anywhere in the system — creates a register record at the moment it
is sent. The watchdog knows what is outstanding because it was TOLD, never
because it looked."*

Two things follow from that, and both are load-bearing:

**The entry is written BEFORE the agent is spawned.** A spawn that dies — the
subprocess never starts, systemd-run refuses, the box loses power — still
leaves evidence that the dispatch was promised. Evidence written after a
successful spawn only ever records the dispatches that were already fine.

**Crash coverage lives here, and it does not poll.** An entry past its
``expected_by`` with no completion record is simply a FACT ABOUT A FILE. Any
reader sees it — ``watchdog status``, the statusline paint, the wire's next
event — and nothing has to be running to discover it. That is what replaced
the detection daemon, and it is what satisfies Patrick's rule 2: *"Idle = zero
running processes."*

APPEND-ONLY. A dispatch is closed by appending a SECOND record carrying the
same ``dispatch_id``, never by rewriting the first. Rewriting would mean a
reader could see the promise disappear, and the promise is the whole point —
the same discipline the notification feed already keeps.

NO CENTRAL REGISTER. Rule 1 says "anywhere in the system", and cross-project
dispatch is blocked by design, so "anywhere" means every project owns a
register at its own ``.aipass/``, discovered exactly the way the feed is.
"""

from __future__ import annotations

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

# Trim policy, mirroring the feed's ceiling: an append-only log still needs a
# ceiling or it grows without bound. Kept larger than the feed's 400/200
# because an outstanding entry must survive long enough for its completion
# record to join it — a dispatch may legitimately run for HARD_TIMEOUT.
REGISTER_MAX_LINES = 2000
REGISTER_KEEP_LINES = 1000

# Record statuses. "outstanding" is written at send; anything else closes it.
STATUS_OUTSTANDING = "outstanding"


def register_file(repo_root: Optional[Path] = None) -> Path:
    """Where this project's dispatch register lives.

    ``repo_root`` re-roots the answer onto another tree — a test's ``tmp_path``,
    or another project — instead of hardcoding a second copy of the location.
    The relative shape is DISCOVERED by walking up from the live answer to the
    repo marker, so nothing here needs to know that the register lives in
    ``.aipass/``; move it and this keeps working.

    Raises:
        RuntimeError: when ``repo_root`` was given but the register's position
            relative to a repo root cannot be determined.

    NEVER THE LIVE PATH when a caller asked for ``repo_root``. Handing a test
    the PRODUCTION register to write into is the defect ``feed.py`` was fixed
    for on 2026-08-21. Here that is STRUCTURAL rather than checked: the return
    below is always rooted at ``repo_root``, so there is no branch that could
    return the live answer by mistake.

    TRANSPLANTED WITH THE ROOT WE ALREADY HOLD, which is the whole point.
    An earlier version re-DERIVED the root by walking ``resolved.parents`` for
    the marker file — asking a second time a question we had just answered. On
    a fresh checkout there is no marker anywhere (the registry is untracked
    runtime state), so the walk found nothing and this RAISED for every
    consumer who passed ``repo_root``: 26 of @devpulse's tests and the CI job
    on PR 739. One root, one answer, no second opinion to disagree with.
    """
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
) -> Optional[str]:
    """Record that a dispatch was promised, and return its id.

    Called BEFORE the spawn. The returned id travels to the agent in its
    environment and comes back on its completion report, which is what makes
    "was this dispatch mine?" answerable from a written record rather than
    inferred from timing.

    Args:
        sender: Who dispatched, e.g. "@devpulse"
        target: Who was dispatched, e.g. "@ai_mail"
        subject: The dispatch subject, for a human reading the register
        expected_seconds: How long this dispatch may legitimately take. Pass
            the dispatch lane's EXISTING timeout — ``dispatch_monitor``'s
            ``HARD_TIMEOUT`` — never a number invented here. That is what makes
            "past expected_by" mean the monitor died rather than "the agent is
            taking a while": a live monitor kills the run at HARD_TIMEOUT and
            writes its report, so it can never legitimately overrun.
        repo_root: Re-root the register (tests, other projects)

    Returns:
        The dispatch id, or None if the register could not be written — the
        caller must still dispatch. A register that cannot record must not
        also be able to CANCEL work; losing the evidence is the smaller
        failure, and it is loud in the log rather than silent.
    """
    json_handler.log_operation("register_open_dispatch", {"sender": sender, "target": target})

    dispatch_id = str(uuid.uuid4())
    now = datetime.now().astimezone()

    record = {
        "dispatch_id": dispatch_id,
        "ts": now.isoformat(),
        "sender": str(sender),
        "target": str(target),
        "subject": str(subject),
        "expected_by": (now + timedelta(seconds=expected_seconds)).isoformat(),
        "status": STATUS_OUTSTANDING,
    }

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


def close_dispatch(
    dispatch_id: str,
    status: str,
    report_path: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> bool:
    """Close an outstanding dispatch by APPENDING a second record.

    The first record is never touched. A reader reconstructs current state by
    reading forward and letting later records win — the same way the feed is
    read — which is what keeps the promise visible even after it is answered.

    Args:
        dispatch_id: The id minted by open_dispatch
        status: How it ended, e.g. "completed" or "FAILED (code 1)"
        report_path: Where the full completion report was written
        repo_root: Re-root the register (tests, other projects)

    Returns:
        True if the closing record was appended
    """
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

    This is the whole of crash detection, and NOTHING RUNS TO PRODUCE IT. The
    staleness is a fact about a file; this function is just someone looking.

    Args:
        repo_root: Re-root the register (tests, other projects)
        now: Comparison instant, injectable so a test does not race the clock

    Returns:
        Open entries, each gaining an ``overdue`` bool. An entry whose
        ``expected_by`` cannot be parsed is returned with ``overdue`` False and
        the reason logged — an unreadable timestamp is not evidence of a crash.

    Raises:
        OSError: when the register EXISTS but cannot be read. A missing register
            yields ``[]`` (nothing has been registered yet, which is honest);
            an unreadable one must not, because a caller cannot tell that
            emptiness apart from "all clear" and would report all-clear.
    """
    moment = now or datetime.now().astimezone()
    open_entries: Dict[str, Dict] = {}

    # strict=True: an unreadable register must NOT return []. "Nothing is
    # outstanding" and "I cannot tell what is outstanding" are opposite answers,
    # and an empty list renders them identically — @devpulse's wire pins the
    # distinction rather than swallowing it, and this is the half that makes
    # their pin possible. Removing the old re-root raise (which fired on every
    # fresh checkout) closed the wrong door on the same question.
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
