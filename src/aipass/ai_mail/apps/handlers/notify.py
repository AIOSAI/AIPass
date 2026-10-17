# =================== AIPass ====================
# Name: notify.py
# Description: Notification Feed Writer
# Version: 2.0.1
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Notification Feed Writer

Append-only JSONL feed BAUD's bell reads; desktop toasts are retired. Reference: docs/dispatch_register_and_feed.md
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

if sys.platform == "win32":
    import msvcrt

    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")
else:
    import fcntl

NOTIFICATION_KINDS = ("mail", "wake", "dispatch", "system")
DEFAULT_KIND = "system"


def feed_path() -> Path:
    """Where the notification feed lives — the one place the path is built."""
    return find_repo_root() / ".aipass" / "notifications.jsonl"


FEED_PATH = feed_path()
FEED_LOCK_NAME = ".notifications.lock"

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

    ``extra`` fields are additive, never overwrite a contract key; @api serves every line to BAUD, so keep them small.
    """
    json_handler.log_operation("send_notification", {"title": title, "source": source, "kind": kind})

    return _append_event(FEED_PATH, _build_event(title, body, source, kind, extra))


def _build_event(
    title: str, body: str, source: str, kind: str, extra: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Build the feed line payload — the whole schema lives here.

    Contract keys are written LAST so an ``extra`` carrying ``ts`` or ``kind`` cannot redefine the schema.
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

    The parameter is *path*, not *feed_path*: shadowing the module function would break ``feed_path()`` here.
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

    One shared write discipline for the feed and the dispatch register, so the lock-then-trim ordering cannot drift.
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

    A malformed line is skipped and named; a missing file yields nothing. ``strict`` raises OSError when an existing
    file cannot be read: for the dispatch register, "nothing outstanding" and "cannot tell" must differ.
    """
    # Checked, not caught: a missing file is a defined empty state, distinct from a read failure below.
    if not path.exists():
        return

    # Read as bytes, decoded per line: one non-UTF-8 line must not fail every line after it.
    try:
        with open(path, "rb") as f:
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
            yield json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("[notify] skipping malformed line %d in %s", number, path)


@contextmanager
def _jsonl_lock(path: Path, lock_name: str):
    """Hold an exclusive advisory lock for an append-only log."""
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

    Caller must hold the lock. os.replace gives a new inode, so readers cannot hold offsets across a trim.
    """
    try:
        with open(path, "rb") as f:
            lines = f.readlines()
    except OSError as e:
        logger.error("[notify] trim could not read %s: %s", path, e)
        return False

    if len(lines) <= max_lines:
        return False

    kept = lines[-keep_lines:]
    temp_path = path.with_name(path.name + ".trim")

    try:
        with open(temp_path, "wb") as f:
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
