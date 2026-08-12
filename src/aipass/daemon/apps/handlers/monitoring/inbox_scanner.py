# =================== AIPass ====================
# Name: inbox_scanner.py
# Description: Cheap cross-branch scan for unread mail sitting past a staleness threshold
# Version: 1.1.0
# Created: 2026-08-11
# Modified: 2026-08-12
# =============================================

"""
Inbox scanner — reads every active branch's .ai_mail.local/inbox.json and
reports which branches are sitting on NEW (unread) mail older than a threshold.

Pure read-only detection: no waking, no mutation. The inbox_sweep module owns
the wake decision. Replies never wake their recipient, so unread mail is
invisible until something looks — this is the thing that looks.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.schedule.discovery import (
    MANAGER_CLASS,
    active_branch_map,
    branch_path_for,
    citizen_class_for,
)

DEFAULT_STALE_HOURS = 24

UNREAD_STATUS = "new"
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

# Skip reason — a branch can be stale but ineligible for a wake.
SKIP_MANAGER = "manager"


def _parse_timestamp(raw: str) -> Optional[datetime]:
    """Parse an ai_mail message timestamp. Returns None if unparseable."""
    if not raw:
        return None

    try:
        return datetime.strptime(raw, TIMESTAMP_FORMAT)
    except (ValueError, TypeError) as e:
        logger.info("[inbox_scanner] Timestamp %r not in mail format (%s) — trying ISO", raw, e)

    try:
        return datetime.fromisoformat(raw)
    except (ValueError, TypeError) as e:
        logger.info("[inbox_scanner] Unparseable timestamp %r (%s) — message skipped", raw, e)
        return None


def _load_inbox(inbox_file: Path) -> Optional[dict]:
    """Read an inbox.json. Returns parsed dict or None on any failure."""
    try:
        with open(inbox_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[inbox_scanner] Failed to read %s: %s", inbox_file, e)
        return None

    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        logger.warning("[inbox_scanner] Malformed inbox structure in %s", inbox_file)
        return None

    return data


def _skip_reason(branch_path: Path, owner: str) -> Optional[str]:
    """Return why this branch must not be woken, or None if it is wakeable.

    Managers are never woken — their mail lands live in an open session. The
    @daemon sender bypasses ai_mail's own manager gate (self-scheduled wakes),
    so the sweep has to enforce the rule itself or it would spawn interactive
    sessions on managers.

    Only passport-local reasons are decided here. ai_mail's wake blocklist is a
    wake-policy concern and is applied by the inbox_sweep module.
    """
    if citizen_class_for(branch_path) == MANAGER_CLASS:
        logger.info("[inbox_scanner] %s is manager-class — not wakeable", owner)
        return SKIP_MANAGER

    return None


def scan_branch_inbox(
    branch_path: Path,
    owner: str,
    now: Optional[datetime] = None,
    stale_hours: int = DEFAULT_STALE_HOURS,
) -> Optional[dict]:
    """
    Scan one branch mailbox for unread mail older than `stale_hours`.

    Returns an entry dict when the branch has stale unread mail, else None.
    """
    if now is None:
        now = datetime.now()

    inbox_file = branch_path / ".ai_mail.local" / "inbox.json"
    if not inbox_file.is_file():
        return None

    data = _load_inbox(inbox_file)
    if data is None:
        return None

    unread = [m for m in data["messages"] if isinstance(m, dict) and m.get("status") == UNREAD_STATUS]
    if not unread:
        return None

    stale = []
    for message in unread:
        sent_at = _parse_timestamp(message.get("timestamp", ""))
        if sent_at is None:
            continue
        age_hours = (now - sent_at).total_seconds() / 3600
        if age_hours >= stale_hours:
            stale.append((age_hours, message))

    if not stale:
        return None

    stale.sort(key=lambda pair: pair[0], reverse=True)
    oldest_age, oldest_message = stale[0]

    return {
        "owner": owner,
        "branch": branch_path.name,
        "path": str(branch_path),
        "unread_total": len(unread),
        "stale_count": len(stale),
        "oldest_age_hours": round(oldest_age, 1),
        "oldest_from": oldest_message.get("from", "?"),
        "oldest_subject": oldest_message.get("subject", "(no subject)"),
        "skip_reason": _skip_reason(branch_path, owner),
    }


def find_stale_inboxes(
    stale_hours: int = DEFAULT_STALE_HOURS,
    now: Optional[datetime] = None,
) -> List[dict]:
    """
    Scan every active, registered branch for stale unread mail.

    Returns entries sorted oldest-first, so the stalest mailbox is served first
    when the sweep caps how many branches it wakes in one pass.
    """
    branch_map = active_branch_map()
    if not branch_map:
        logger.warning("[inbox_scanner] No active branches found in registry")
        return []

    entries = []
    for dir_name in sorted(branch_map):
        entry = scan_branch_inbox(
            branch_path_for(dir_name),
            branch_map[dir_name],
            now=now,
            stale_hours=stale_hours,
        )
        if entry is not None:
            entries.append(entry)

    entries.sort(key=lambda e: e["oldest_age_hours"], reverse=True)

    logger.info(
        "[inbox_scanner] %d branch(es) with mail unread past %dh (of %d scanned)",
        len(entries),
        stale_hours,
        len(branch_map),
    )
    json_handler.log_operation("scan_stale_inboxes", {"stale": len(entries), "scanned": len(branch_map)})
    return entries
