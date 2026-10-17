# =================== AIPass ====================
# Name: feed.py
# Description: Host API Feed Handler — cursor-first notification feed reads
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""Host API Feed Handler
Reference: docs/host_surfaces.md (why the cursor is a timestamp, never an offset)."""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# @ai_mail owns the feed's location and shape; their door moves it and this follows.
import aipass.ai_mail as ai_mail


def feed_path() -> Path:
    """Locate @ai_mail's notification feed.
    Thin by design: their door is the authority; this keeps the seam patchable in tests."""
    return Path(ai_mail.feed_path())


DEFAULT_LIMIT = 100
MAX_LIMIT = 500

GAP_TRIMMED = "feed_trimmed"


class FeedUnavailable(Exception):
    """The feed could not be read. Reported honestly, never faked as empty."""


def read_feed(since: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Read a cursor-first window of notification events."""
    limit = max(1, min(int(limit), MAX_LIMIT))

    events = _load_events()

    if not events:
        return _envelope([], since, gap=False, more=False)

    # _load_events only keeps entries with a truthy ts, so these are real strings.
    oldest_ts = str(events[0]["ts"])
    newest_ts = str(events[-1]["ts"])

    if since is None:
        window = events[-limit:]
        return _envelope(window, newest_ts, gap=False, more=len(events) > limit)

    if since < oldest_ts:
        # The trim ate unseen events: flag the gap, or the phone silently under-reports.
        logger.warning(
            "[host_api] feed cursor %s predates the feed (oldest %s) — clamping, gap flagged",
            since,
            oldest_ts,
        )
        window = events[:limit]
        return _envelope(window, window[-1].get("ts"), gap=True, gap_reason=GAP_TRIMMED, more=len(events) > limit)

    if since > newest_ts:
        logger.warning(
            "[host_api] feed cursor %s is ahead of the feed (newest %s) — clamping to latest",
            since,
            newest_ts,
        )
        return _envelope([], newest_ts, gap=False, more=False)

    # >= not >: ts can tie, so the boundary event is re-delivered; clients dedupe on (ts, kind, title).
    matched = [event for event in events if event.get("ts", "") >= since]
    window = matched[:limit]

    cursor = window[-1].get("ts") if window else since
    return _envelope(window, cursor, gap=False, more=len(matched) > limit)


def _load_events() -> List[Dict[str, Any]]:
    """Parse the feed into events, in file order.
    Never re-sorted: a sort would shuffle tied timestamps and make the cursor non-monotonic."""
    path = feed_path()

    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("[host_api] feed could not be read at %s: %s", path, e)
        raise FeedUnavailable(f"Notification feed could not be read: {e}") from e

    events: List[Dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.info("[host_api] skipping malformed feed line %d", index)
            continue
        if isinstance(event, dict) and event.get("ts"):
            events.append(event)

    return events


def _envelope(
    events: List[Dict[str, Any]],
    cursor: Optional[str],
    *,
    gap: bool,
    gap_reason: Optional[str] = None,
    more: bool = False,
) -> Dict[str, Any]:
    """Build the response envelope and write the delivery receipt.
    The receipt makes a disagreement between what was sent and what the phone shows auditable."""
    digest = hashlib.sha256(
        "".join(f"{event.get('ts')}|{event.get('kind')}|{event.get('title')}" for event in events).encode("utf-8")
    ).hexdigest()[:16]

    json_handler.log_operation(
        "host_api_feed_read",
        {"delivered": len(events), "cursor": cursor, "gap": gap, "more": more, "digest": digest},
    )

    return {
        "events": events,
        "cursor": cursor,
        "gap": gap,
        "gap_reason": gap_reason,
        "more": more,
    }
