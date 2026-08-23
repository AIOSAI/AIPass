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

Locate the feed via ``aipass.ai_mail.feed_path()``, not by restating the path.
Readers: the trim REPLACES the file, so the inode changes and line positions
shift. Lines carry no id, so a cursor held as a line index or byte offset goes
stale silently. Key on ``ts`` and flag gaps — full contract in the README.

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
from typing import Dict, Optional

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


def feed_path() -> Path:
    """Where the notification feed lives — the one place the path is built.

    @api serves this file over /v1/feed and had restated the expression as
    their own constant, because reaching into another branch's handlers is an
    encapsulation violation. A duplicated path goes stale silently the day the
    feed moves: a phone bell showing nothing, with no error anywhere. The door
    is re-exported as ``aipass.ai_mail.feed_path``.

    Prefer this over FEED_PATH in new code — it resolves at call time, while
    the constant freezes the repo root at import.
    """
    return find_repo_root() / ".aipass" / "notifications.jsonl"


FEED_PATH = feed_path()
FEED_LOCK_NAME = ".notifications.lock"

# Trim policy: once the feed passes FEED_MAX_LINES, keep only the newest
# FEED_KEEP_LINES. A bell shows recent events — old ones have no reader.
FEED_MAX_LINES = 400
FEED_KEEP_LINES = 200


def send_notification(
    title: str,
    body: str,
    source: str = "ai_mail",
    kind: str = DEFAULT_KIND,
    extra: Optional[Dict[str, str]] = None,
) -> bool:
    """Append one notification event to the shared feed.

    Args:
        title: Event title (e.g. "DEVPULSE -> AI_MAIL")
        body: Event body text
        source: Branch the event is about, with or without a leading @
        kind: One of NOTIFICATION_KINDS; anything else is logged and
              recorded as "system" rather than dropped
        extra: Additive fields merged into the line — never overwriting a
               contract key. Dispatch completions carry ``dispatch_id``,
               ``sender`` and ``report_path`` this way (FPLAN-0452 P1), so a
               reader can tell whose dispatch finished and where the full
               report waits WITHOUT the 1-2 KB report bloating every line.
               @api serves this feed to BAUD, so growth here is not free.

    Returns:
        True if the line was appended, False if the feed write failed
    """
    json_handler.log_operation("send_notification", {"title": title, "source": source, "kind": kind})

    return _append_event(FEED_PATH, _build_event(title, body, source, kind, extra))


def _build_event(
    title: str, body: str, source: str, kind: str, extra: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Build the feed line payload — the whole schema lives here.

    Contract keys are written LAST so an ``extra`` carrying ``ts`` or ``kind``
    cannot quietly redefine the schema every reader depends on.
    """
    event: Dict[str, str] = {}
    if extra:
        event.update({str(k): v for k, v in extra.items() if v is not None})

    event.update(
        {
            "ts": datetime.now().astimezone().isoformat(),
            "kind": _normalize_kind(kind),
            "title": str(title),
            "body": str(body),
            "source": str(source).lstrip("@").strip(),
        }
    )
    return event


def _normalize_kind(kind: str) -> str:
    """Return a contract-valid kind, naming the substitution when one happens."""
    if kind in NOTIFICATION_KINDS:
        return kind

    logger.warning("[notify] unknown kind %r — recording as %r", kind, DEFAULT_KIND)
    return DEFAULT_KIND


def _append_event(path: Path, event: Dict[str, str]) -> bool:
    """Append *event* as one JSON line, then trim if the feed has outgrown its cap.

    The parameter is *path*, not *feed_path*: that name belongs to the module
    function above, and shadowing it here would make ``feed_path()`` inside
    this body a TypeError on a Path.
    """
    return append_jsonl(
        path,
        event,
        lock_name=FEED_LOCK_NAME,
        max_lines=FEED_MAX_LINES,
        keep_lines=FEED_KEEP_LINES,
    )


def append_jsonl(path: Path, record: Dict, *, lock_name: str, max_lines: int, keep_lines: int) -> bool:
    """Append *record* as one locked JSON line to a capped append-only log.

    The feed's write discipline, made reusable rather than copied. The dispatch
    register (FPLAN-0452 P0) is the same shape — append-only, locked, capped —
    and a second hand-rolled copy of the lock-then-trim ordering is how the two
    drift apart: fix a race in one and the other keeps it.

    Args:
        path: The log file; its parent is created if missing
        record: One JSON-serialisable record
        lock_name: Sibling lock filename, so two logs never share a lock
        max_lines: Trim once the file passes this many lines
        keep_lines: How many newest lines a trim keeps

    Returns:
        True if the line was appended, False if the write failed
    """
    line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _jsonl_lock(path, lock_name):
            fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
            _trim_jsonl(path, max_lines, keep_lines)
        return True
    except OSError as e:
        logger.error("[notify] jsonl write failed for %s: %s", path, e)
        return False


def jsonl_records(path: Path, strict: bool = False):
    """Yield each parseable record from a JSONL log, oldest first.

    A malformed line is skipped and named rather than aborting the read: these
    logs are appended by concurrent processes, and one truncated line must not
    cost a reader every record after it. A missing file yields nothing — that
    is a defined empty state ("nothing registered yet"), not a failure.

    Args:
        path: The JSONL log to read
        strict: Raise OSError when an EXISTING file cannot be read, instead of
            logging and yielding nothing. Callers whose emptiness is meaningful
            need this: for the dispatch register, "nothing is outstanding" and
            "I cannot tell what is outstanding" are opposite answers, and
            returning an empty sequence for both renders them identically.
            @devpulse pinned that distinction in their wire (2026-08-22) and it
            is theirs to rely on. The feed keeps the tolerant default — a bell
            that misses events is better than one that raises at a hook.
    """
    # Checked, not caught: "nothing has been registered yet" is a DEFINED EMPTY
    # STATE, and an empty generator says so honestly. Swallowing FileNotFoundError
    # would make it indistinguishable from a real read failure one line below.
    if not path.exists():
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        if strict:
            raise
        logger.error("[notify] jsonl read failed for %s: %s", path, e)
        return

    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            logger.warning("[notify] skipping malformed line %d in %s", number, path)


@contextmanager
def _jsonl_lock(path: Path, lock_name: str):
    """Hold an exclusive advisory lock for an append-only log.

    The lock lives on a sibling lock file, never on the log itself — the trim
    replaces the log's inode, which would drop a lock held on it.
    """
    lock_file = path.parent / lock_name
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


def _trim_jsonl(path: Path, max_lines: int, keep_lines: int) -> bool:
    """Drop an append-only log to its newest *keep_lines* once past *max_lines*.

    Caller must hold the log's lock — this is a read-modify-write, and an
    unlocked append landing between the read and the replace would be lost.

    The os.replace below gives the log a NEW INODE. Readers therefore cannot
    hold a byte offset or line index across a trim; the feed's reader contract
    in the README says key on ``ts``, and the register is read whole.

    Returns:
        True if the log was trimmed, False if it was already within cap
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        logger.error("[notify] trim could not read %s: %s", path, e)
        return False

    if len(lines) <= max_lines:
        return False

    kept = lines[-keep_lines:]
    temp_path = path.with_name(path.name + ".trim")

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(str(temp_path), str(path))
    except OSError as e:
        logger.error("[notify] trim failed for %s: %s", path, e)
        temp_path.unlink(missing_ok=True)
        return False

    logger.info("[notify] %s trimmed %d -> %d lines", path.name, len(lines), len(kept))
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
