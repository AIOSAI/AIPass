# =================== AIPass ====================
# Name: notify.py
# Description: Notification Feed Writer
# Version: 2.0.0
# Created: 2026-03-08
# Modified: 2026-08-11
# =============================================

"""
Notification Feed Writer

Desktop toasts are retired (Patrick's ruling, 2026-08-11) — no D-Bus, no
notify-send, and no fallback that still toasts. Notification events are
appended as JSON lines to a shared feed; BAUD's notification bell reads it.

Feed contract (ai_mail writes, BAUD reads):

    path : <repo root>/.aipass/notifications.jsonl
    line : {"ts": ISO8601, "kind": mail|wake|dispatch|system,
            "title": str, "body": str, "source": branch name (no @)}

Append-only, one JSON object per line. Readers never write, and the feed
carries no read flags — BAUD tracks read state locally.

Concurrency: delivery, wake, dispatch_monitor and daemon append from separate
processes. Each append is a single O_APPEND write; the trim is a
read-modify-write. Both take the same advisory lock, so an append can never
land inside a trim and be dropped.

Fail honest: a feed write that fails is logged and returns False. Nothing
falls back to a toast.
"""

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.handlers.paths import find_repo_root

# fcntl is POSIX-only (Linux/macOS). On Windows, use msvcrt for locking.
if sys.platform == "win32":
    import msvcrt

    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")
else:
    import fcntl

# The four event kinds BAUD renders. Anything else is coerced to "system".
NOTIFICATION_KINDS = ("mail", "wake", "dispatch", "system")
DEFAULT_KIND = "system"

FEED_PATH = find_repo_root() / ".aipass" / "notifications.jsonl"
FEED_LOCK_NAME = ".notifications.lock"

# Trim policy: once the feed passes FEED_MAX_LINES, keep only the newest
# FEED_KEEP_LINES. A bell shows recent events — old ones have no reader.
FEED_MAX_LINES = 400
FEED_KEEP_LINES = 200


def send_notification(title: str, body: str, source: str = "ai_mail", kind: str = DEFAULT_KIND) -> bool:
    """Append one notification event to the shared feed.

    Args:
        title: Event title (e.g. "DEVPULSE -> AI_MAIL")
        body: Event body text
        source: Branch the event is about, with or without a leading @
        kind: One of NOTIFICATION_KINDS; anything else is logged and
              recorded as "system" rather than dropped

    Returns:
        True if the line was appended, False if the feed write failed
    """
    json_handler.log_operation("send_notification", {"title": title, "source": source, "kind": kind})

    return _append_event(FEED_PATH, _build_event(title, body, source, kind))


def _build_event(title: str, body: str, source: str, kind: str) -> Dict[str, str]:
    """Build the feed line payload — the whole schema lives here."""
    return {
        "ts": datetime.now().astimezone().isoformat(),
        "kind": _normalize_kind(kind),
        "title": str(title),
        "body": str(body),
        "source": str(source).lstrip("@").strip(),
    }


def _normalize_kind(kind: str) -> str:
    """Return a contract-valid kind, naming the substitution when one happens."""
    if kind in NOTIFICATION_KINDS:
        return kind

    logger.warning("[notify] unknown kind %r — recording as %r", kind, DEFAULT_KIND)
    return DEFAULT_KIND


def _append_event(feed_path: Path, event: Dict[str, str]) -> bool:
    """Append *event* as one JSON line, then trim if the feed has outgrown its cap."""
    line = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        feed_path.parent.mkdir(parents=True, exist_ok=True)
        with _feed_lock(feed_path):
            fd = os.open(str(feed_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
            _trim_feed(feed_path)
        return True
    except OSError as e:
        logger.error("[notify] feed write failed for %s: %s", feed_path, e)
        return False


@contextmanager
def _feed_lock(feed_path: Path):
    """Hold an exclusive advisory lock for the feed.

    The lock lives on a sibling .notifications.lock file, never on the feed
    itself — the trim replaces the feed inode, which would drop a lock held
    on it.
    """
    lock_file = feed_path.parent / FEED_LOCK_NAME
    lock_fd = None

    try:
        lock_fd = open(lock_file, "w", encoding="utf-8")
        if sys.platform == "win32":
            msvcrt.locking(lock_fd.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            try:
                if sys.platform == "win32":
                    msvcrt.locking(lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            except OSError as e:
                logger.warning("[notify] feed lock release failed: %s", e)
            finally:
                lock_fd.close()


def _trim_feed(feed_path: Path) -> bool:
    """Drop the feed to its newest FEED_KEEP_LINES once past FEED_MAX_LINES.

    Caller must hold the feed lock — this is a read-modify-write, and an
    unlocked append landing between the read and the replace would be lost.

    Returns:
        True if the feed was trimmed, False if it was already within cap
    """
    try:
        with open(feed_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        logger.error("[notify] feed trim could not read %s: %s", feed_path, e)
        return False

    if len(lines) <= FEED_MAX_LINES:
        return False

    kept = lines[-FEED_KEEP_LINES:]
    temp_path = feed_path.with_name(feed_path.name + ".trim")

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(str(temp_path), str(feed_path))
    except OSError as e:
        logger.error("[notify] feed trim failed for %s: %s", feed_path, e)
        temp_path.unlink(missing_ok=True)
        return False

    logger.info("[notify] feed trimmed %d -> %d lines", len(lines), len(kept))
    return True


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print("\n" + "=" * 70)
    console.print("NOTIFICATION FEED WRITER")
    console.print("=" * 70)
    console.print(f"\nFeed path: {FEED_PATH}")
    console.print(f"Kinds: {', '.join(NOTIFICATION_KINDS)}")
    console.print(f"Trim: newest {FEED_KEEP_LINES} lines once past {FEED_MAX_LINES}")
    console.print("\nFunctions provided:")
    console.print("  - send_notification(title, body, source, kind) -> bool")
    console.print()
