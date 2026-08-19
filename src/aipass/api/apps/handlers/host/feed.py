# =================== AIPass ====================
# Name: feed.py
# Description: Host API Feed Handler — cursor-first notification feed reads
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Feed Handler

The read lane's notification feed (FPLAN-0411 design call D3). The phone polls
this after a push wakes it: "what did I miss since cursor X".

WHY THE CURSOR IS A TIMESTAMP AND NOT AN OFFSET
-----------------------------------------------
@ai_mail's feed is trimmed — FEED_MAX_LINES 400 down to FEED_KEEP_LINES 200 —
and the trim writes a temp file and REPLACES THE FEED, so the inode changes. The
lines carry no id of their own. A cursor that was a line index or a byte offset
would therefore go stale on every trim and point past a file that shrank
underneath it. That is precisely the shape of the TG 10-hour outage (a cursor
ahead of a compacted transcript, retrying forever), and building the phone's
read lane on an offset would have re-filed the same bug in a new branch.

So: the cursor is the `ts` of the last event the client received, and it CLAMPS
in both directions rather than ever spinning or erroring.

    cursor older than the feed's oldest line -> the trim ate the window.
        Clamp to oldest, return gap=True. The phone says "some events were
        trimmed" instead of quietly showing fewer notifications than happened.

    cursor newer than the feed's newest line -> clock skew, or the feed was
        replaced. Clamp, return empty, log it. Deliver, never spin.

AT-LEAST-ONCE ON PURPOSE: the boundary event (ts == cursor) is re-delivered
rather than skipped, because two events can share a microsecond and dropping one
is worse than showing one twice. Clients dedupe on (ts, kind, title).

The feed's location and field shape are @ai_mail's — this handler moves their
data, it does not define it. The location comes from their own published door,
so if they move the file, this follows without an edit.

Functions:
    read_feed() - Cursor-first window over the feed
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# @ai_mail owns this feed, and now owns the answer to where it is. This used to
# restate their documented path as a constant, with a note asking them to publish
# a door so the comment could become an import. They built it (2026-08-16), so
# this is that import: one implementation of the location, on the side that gets
# to move it.
import aipass.ai_mail as ai_mail


def feed_path() -> Path:
    """
    Locate @ai_mail's notification feed.

    Thin by design. Their door is the authority; this wrapper exists only so the
    seam stays patchable in tests and so a future change of theirs lands in one
    place here rather than at every call site.

    Returns:
        Absolute path to the feed file.
    """
    return Path(ai_mail.feed_path())


DEFAULT_LIMIT = 100
MAX_LIMIT = 500

GAP_TRIMMED = "feed_trimmed"


class FeedUnavailable(Exception):
    """The feed could not be read. Reported honestly, never faked as empty."""


def read_feed(since: Optional[str] = None, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """
    Read a cursor-first window of notification events.

    Args:
        since: Cursor — the ts of the last event the caller received. None means
            "give me the most recent window".
        limit: Maximum events to return. Clamped to MAX_LIMIT.

    Returns:
        Dict with:
            events     - list of feed events, oldest first
            cursor     - ts to send as `since` on the next poll
            gap        - True if events were lost to the trim before we read
            gap_reason - why, when gap is True
            more       - True if the limit truncated the window (poll again)

    Raises:
        FeedUnavailable: The feed exists but could not be read.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))

    events = _load_events()

    if not events:
        return _envelope([], since, gap=False, more=False)

    # _load_events only keeps entries with a truthy ts, so these are real strings.
    oldest_ts = str(events[0]["ts"])
    newest_ts = str(events[-1]["ts"])

    if since is None:
        # First contact: the most recent window, not the whole file.
        window = events[-limit:]
        return _envelope(window, newest_ts, gap=False, more=len(events) > limit)

    if since < oldest_ts:
        # The trim ate everything the caller had not seen yet. Say so out loud —
        # silently returning what survives is how a phone under-reports.
        logger.warning(
            "[host_api] feed cursor %s predates the feed (oldest %s) — clamping, gap flagged",
            since,
            oldest_ts,
        )
        window = events[:limit]
        return _envelope(window, window[-1].get("ts"), gap=True, gap_reason=GAP_TRIMMED, more=len(events) > limit)

    if since > newest_ts:
        # Ahead of the feed. Clamp and deliver nothing rather than spin.
        logger.warning(
            "[host_api] feed cursor %s is ahead of the feed (newest %s) — clamping to latest",
            since,
            newest_ts,
        )
        return _envelope([], newest_ts, gap=False, more=False)

    # >= not >: the boundary event is re-delivered. A duplicate is a nuisance,
    # a dropped alert is the failure this whole surface exists to prevent.
    matched = [event for event in events if event.get("ts", "") >= since]
    window = matched[:limit]

    cursor = window[-1].get("ts") if window else since
    return _envelope(window, cursor, gap=False, more=len(matched) > limit)


# ==============================================
# PRIVATE HELPERS
# ==============================================


def _load_events() -> List[Dict[str, Any]]:
    """
    Parse the feed into events, in file order.

    File order IS time order (append-only), so nothing is re-sorted — a re-sort
    would shuffle events sharing a timestamp and make the cursor non-monotonic.

    Returns:
        List of event dicts carrying a 'ts'.

    Raises:
        FeedUnavailable: The feed could not be read.
    """
    path = feed_path()

    if not path.exists():
        # No feed yet is a real, quiet state — not an error.
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
    """
    Build the response envelope and write the delivery receipt.

    The receipt records intended vs delivered so a disagreement between what the
    server sent and what the phone shows is auditable rather than a guess.

    Args:
        events: Events being returned.
        cursor: Cursor for the caller's next poll.
        gap: Whether events were lost before we read.
        gap_reason: Why, when gap is True.
        more: Whether the limit truncated the window.

    Returns:
        The response envelope.
    """
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
