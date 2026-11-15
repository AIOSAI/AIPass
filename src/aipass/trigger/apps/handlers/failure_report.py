# =================== AIPass ====================
# Name: failure_report.py
# Description: The loud route for a failure its caller must survive: trail line, medic status row, one mail
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""
Failure report - the bus and the log watcher must keep running past a failure, so they report it here.

Each (name, branch) failure writes an ERROR line to logs/failures.jsonl at most once per interval.
Its first failure adds a medic status row and mails the manager once per name; a success clears both.
"""

from time import monotonic

from aipass.prax import trail
from aipass.trigger.apps.config import TRIGGER_ROOT
from aipass.trigger.apps.handlers import medic_state
from aipass.trigger.apps.handlers.ci import outbound
from aipass.trigger.apps.handlers.json import json_handler

FAILURES_LOG = TRIGGER_ROOT / "logs" / "failures.jsonl"
# Trail: a failure line on a watched log would re-enter the watcher or the bus that just failed.
logger = trail(FAILURES_LOG)
LOG_INTERVAL_SECONDS = 600.0

_counts: dict = {}  # (name, branch) -> consecutive failures
_logged_at: dict = {}  # (name, branch) -> monotonic time of its last line


def report_failure(name: str, branch: str, event: str, exc: BaseException) -> int:
    """Report one failure of *name* on *branch*; return its count in a row."""
    key = (name, branch)
    count = _counts.get(key, 0) + 1
    _counts[key] = count
    now = monotonic()
    last = _logged_at.get(key)
    if last is None or now - last >= LOG_INTERVAL_SECONDS:
        _logged_at[key] = now
        logger.error(
            f"{name} failed for {event} (branch '{branch}', {count} in a row): {exc}",
            handler=name,
            branch=branch,
            event=event,
            count=count,
        )
    if count == 1:
        json_handler.log_operation("failure_reported", {"name": name, "branch": branch, "event": event})
        _tell(name, branch, event, exc)
    return count


def _tell(name: str, branch: str, event: str, exc: BaseException) -> None:
    """Add the medic status row; mail the manager when no live process had *name* failing."""
    try:
        first = medic_state.record_handler_failure(name, branch, event, str(exc))
    except Exception as record_exc:
        logger.error(f"Could not record that {name} is failing: {record_exc}", handler=name, branch=branch)
        first = True  # no status row to read, so the mail is the only word
    if not first:
        return
    subject = f"[TRIGGER] {name} failing"
    body = (
        f"{name} raised on {event} for branch '{branch}': {exc}\n\n"
        f"It keeps running and logs at most once per {int(LOG_INTERVAL_SECONDS)}s to {FAILURES_LOG.name}. "
        "Every failing branch: drone @trigger medic status."
    )
    if not outbound.mail(outbound.MANAGER, subject, body):
        logger.error(f"Could not mail {outbound.MANAGER} that {name} is failing", handler=name, branch=branch)


def report_recovery(name: str, branch: str) -> None:
    """Clear a recovered (name, branch); a no-op when it was not failing."""
    key = (name, branch)
    if _counts.pop(key, None) is None:
        return
    _logged_at.pop(key, None)
    try:
        medic_state.clear_handler_failure(name, branch)
    except Exception as exc:
        # The stale row stays in medic status, saying failing: loud, and gone when this process ends.
        logger.error(f"Could not clear recovered {name} from medic status: {exc}", handler=name, branch=branch)
        return
    logger.info(f"{name} recovered for branch '{branch}'", handler=name, branch=branch)
