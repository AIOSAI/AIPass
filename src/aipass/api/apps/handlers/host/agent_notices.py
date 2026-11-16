# =================== AIPass ====================
# Name: agent_notices.py
# Description: Host API Agent Notices — a seat's delivered mail, from @ai_mail's feed, as chat notice lines
# Version: 1.0.0
# Created: 2026-11-16
# Modified: 2026-11-16
# =============================================

"""
Host API Agent Notices
Reference: docs/host_agent_chat.md; @ai_mail's dispatch_register_and_feed.md and mail_kinds.md are the contract.
"""

import bisect
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Sequence, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.feed import feed_path

ROUTINE_KIND = "notice"
TEXT_CAP = 120
# A transcript row is stamped before it is written (an assistant reply at its start), so placement waits this long.
SETTLE = timedelta(seconds=2)
EARLIEST = datetime.min.replace(tzinfo=timezone.utc)

# The feed is trimmed past 400 lines; it is parsed again only when its inode, size or mtime moved.
_cache: Dict[str, Any] = {"key": None, "events": []}


def _when(stamp: Any) -> datetime:
    """An ISO 8601 stamp as an aware datetime, a naive one read as local time; EARLIEST when it is not one."""
    if not isinstance(stamp, str):
        return EARLIEST
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        logger.info("[host_api] an unreadable stamp %r is placed first", stamp)
        return EARLIEST
    return when if when.tzinfo else when.astimezone()


def _mail_lines(raw: bytes) -> List[Dict[str, Any]]:
    """The kind "mail" lines of the feed's bytes, a bad line logged and skipped."""
    events = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.info("[host_api] skipped a bad notification feed line: %s", exc)
            continue
        if isinstance(event, dict) and event.get("kind") == "mail":
            events.append(event)
    return events


def _events() -> List[Dict[str, Any]]:
    """The feed's mail lines; [] with one error log per new failure when the file is missing or unreadable."""
    path = feed_path()
    try:
        stat = path.stat()
        key: Any = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
        if key != _cache["key"]:
            _cache.update(key=key, events=_mail_lines(path.read_bytes()))
            json_handler.log_operation("host_api_agent_notices_read", {"mail": len(_cache["events"])})
    except OSError as exc:
        if _cache["key"] != str(exc):
            logger.error("[host_api] the notification feed is unreadable, agent feeds go without notices: %s", exc)
        _cache.update(key=str(exc), events=[])
    return _cache["events"]


def seat_notices(project: str, name: str) -> List[Dict[str, Any]]:
    """The seat's delivered mail in feed order, the routine kind left out; project and name match case-blind."""
    seat = (project.casefold(), name.casefold())
    return [
        event
        for event in _events()
        if (str(event.get("project")).casefold(), str(event.get("recipient")).casefold()) == seat
        and event.get("mail_kind") != ROUTINE_KIND
    ]


def _line(n: int, event: Dict[str, Any]) -> Dict[str, Any]:
    """One notice line: the mail kind as written, who it is from and the subject."""
    subject = str(event.get("body") or event.get("title") or "").split("\n")[0].strip()
    return {
        "n": n,
        "role": "notice",
        "kind": event.get("mail_kind"),
        "text": f"@{event.get('source') or '?'}: {subject}"[:TEXT_CAP],
        "time": event.get("ts"),
        "mail_id": event.get("mail_id"),
    }


def place(spans: Sequence[Tuple[int, int, int, Any]], notices: List[Dict[str, Any]], quiet: bool) -> List[dict]:
    """Notice lines for *spans*, (offset, length, lines made, stamp) per transcript row: docs/host_agent_chat.md.

    A notice goes before the first row whose latest stamp so far passes its own by SETTLE; none yet, it waits
    while the agent works. A gap's notices take n = row offset + lines made + 0, 1, ... in feed order."""
    marks: List[datetime] = []
    for _, _, _, stamp in spans:
        marks.append(max(_when(stamp), marks[-1]) if marks else _when(stamp))
    now, taken, out = datetime.now().astimezone(), {}, []
    for event in notices:
        when = _when(event.get("ts"))
        after = bisect.bisect_right(marks, when + SETTLE)
        if after == len(marks) and not (quiet and now >= when + SETTLE):
            continue
        gap = after - 1
        if gap < 0 or when == EARLIEST:
            continue
        offset, length, made, _ = spans[gap]
        n = offset + made + taken.get(gap, 0)
        if n > offset + length:
            # shortcut: a gap holds as many notices as its row has bytes; past that one is left out, logged.
            logger.warning("[host_api] notice %s left out: its gap is full", event.get("mail_id"))
            continue
        taken[gap] = taken.get(gap, 0) + 1
        out.append(_line(n, event))
    return out
