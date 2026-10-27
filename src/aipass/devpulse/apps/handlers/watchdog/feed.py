# =================== AIPass ====================
# Name: feed.py
# Description: Watchdog Feed Handler — read completions off the push feed instead of polling for them
# Version: 1.2.0
# Created: 2026-08-21
# Modified: 2026-10-26
# =============================================

# The cursor is a set of line digests, never wire.py's byte offset: @ai_mail's
# trim rewrites this feed via os.replace, a new inode with every position moved.

"""Watchdog Feed Handler — the push side of completion detection."""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.json import json_handler
from aipass import ai_mail as _ai_mail


# "mail" is excluded: every email writes one, and a wake per email gets the wire muted.
FEED_KINDS = ("dispatch", "wake")

# Matches @ai_mail's FEED_MAX_LINES, so no digest ages out while its line is on disk.
CURSOR_KEEP_DIGESTS = 400

_DIGEST_CHARS = 16

# Must match @ai_mail's find_repo_root order; the registry is absent on a fresh checkout.
_ROOT_MARKERS = ("AIPASS_REGISTRY.json", "pyproject.toml")

WIRE_CURSOR_NAME = "feed_cursor.json"


def feed_file(repo_root: Path | None = None) -> Path:
    """The notification feed's path, resolved through @ai_mail's public door."""
    resolved = _ai_mail.feed_path()
    if repo_root is None:
        return resolved

    for marker in _ROOT_MARKERS:
        for parent in resolved.parents:
            if (parent / marker).exists():
                return repo_root / resolved.relative_to(parent)

    # No fallback: the live path would hand a repo_root caller the production feed.
    raise RuntimeError(
        f"cannot re-root the notification feed onto {repo_root}: none of {_ROOT_MARKERS} "
        f"found above {resolved}, so its position relative to a repo root is unknown. "
        f"Pass feed_file_path explicitly, or omit repo_root to use the live feed deliberately."
    )


def cursor_file_for(repo_root: Path, name: str = WIRE_CURSOR_NAME, seat: str | None = None) -> Path:
    """Where a reader remembers which feed lines it has already delivered.

    Keep ``name``, and pass ``seat`` for a per-seat reader: two readers on one cursor silently
    steal each other's events (every line drained is marked seen, delivered or not).
    """
    filename = f"{seat.lstrip('@')}.{name}" if seat else name
    return repo_root.joinpath("src", "aipass", "devpulse", "devpulse_json", filename)


def _digest(raw_line: str) -> str:
    """Content key for one feed line — the idempotency key the feed omits."""
    return hashlib.sha256(raw_line.encode("utf-8", errors="replace")).hexdigest()[:_DIGEST_CHARS]


def _read_cursor(cursor_file: Path) -> dict:
    """Load the delivery cursor. An unreadable cursor starts fresh, never wedges.

    Fresh means the next drain seeds: every line on disk is absorbed, not delivered, unless the
    caller passes ``seed_if_new=False``.
    """
    try:
        data = json.loads(cursor_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("[watchdog.feed] no cursor at %s — first drain for this reader", cursor_file)
        return {"seen": [], "seeded": False}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "[watchdog.feed] cursor unreadable %s — starting fresh, disk lines are seeded: %s", cursor_file, exc
        )
        return {"seen": [], "seeded": False}

    seen = data.get("seen")
    if not isinstance(seen, list):
        logger.warning("[watchdog.feed] cursor has no usable digest list — starting fresh, lines on disk are seeded")
        return {"seen": [], "seeded": False}

    return {
        "seen": [d for d in seen if isinstance(d, str)],
        "seeded": bool(data.get("seeded")),
        "stat": data.get("stat"),
    }


def _write_cursor(cursor_file: Path, seen: list[str], stat_key: list | None) -> None:
    """Persist the cursor atomically (tmp + replace)."""
    cursor_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = cursor_file.with_suffix(".json.tmp")
    payload = {
        "seen": seen[-CURSOR_KEEP_DIGESTS:],
        "seeded": True,
        "stat": stat_key,
        "updated": datetime.now().isoformat(timespec="seconds"),
    }
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, cursor_file)


def _stat_key(path: Path) -> list | None:
    """(mtime_ns, size) — the cheap "did anything change" probe."""
    try:
        st = path.stat()
    except OSError as exc:
        logger.debug("[watchdog.feed] feed not stat-able %s: %s", path, exc)
        return None
    return [st.st_mtime_ns, st.st_size]


def drain_feed(
    cursor_file: Path,
    kinds: tuple[str, ...] = FEED_KINDS,
    feed_file_path: Path | None = None,
    seed_if_new: bool = True,
    state: dict | None = None,
    repo_root: Path | None = None,
) -> tuple[list[dict], dict]:
    """Return feed events not yet delivered, newest last.

    In a loop, pass the returned cursor back as ``state`` or every idle tick re-reads the file.
    """
    path = feed_file_path if feed_file_path is not None else feed_file(repo_root)
    cursor = state if state is not None else _read_cursor(cursor_file)

    stat_key = _stat_key(path)
    if stat_key is None:
        return [], cursor
    if stat_key == cursor.get("stat"):
        return [], cursor

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("[watchdog.feed] feed unreadable %s: %s", path, exc)
        return [], cursor

    seen = set(cursor["seen"])
    first_look = not cursor["seeded"]

    delivered: list[dict] = []
    all_digests: list[str] = []

    for raw_line in raw.splitlines():
        text = raw_line.strip()
        if not text:
            continue
        key = _digest(text)
        all_digests.append(key)
        if key in seen:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning("[watchdog.feed] unparseable feed line skipped: %s (%s)", text[:120], exc)
            continue
        if not isinstance(record, dict):
            continue
        if first_look and seed_if_new:
            continue
        if record.get("kind") not in kinds:
            continue
        record["digest"] = key
        delivered.append(record)

    _write_cursor(cursor_file, all_digests, stat_key)
    new_cursor = {"seen": all_digests[-CURSOR_KEEP_DIGESTS:], "seeded": True, "stat": stat_key}

    if first_look and seed_if_new:
        logger.info("[watchdog.feed] first drain — absorbed %d existing lines without delivering", len(all_digests))
    if delivered:
        json_handler.log_operation("drain_feed", {"delivered": len(delivered), "kinds": list(kinds)})

    return delivered, new_cursor


def format_feed_event(record: dict) -> str:
    """Render one feed event as a single wire line."""
    kind = str(record.get("kind") or "?")
    source = str(record.get("source") or "?").lstrip("@")
    title = " ".join(str(record.get("title") or "?").split()).replace('"', "'")
    body = " ".join(str(record.get("body") or "").split()).replace('"', "'")
    line = f'{kind.upper()} @{source} title="{title}"'
    if body:
        line += f' detail="{body}"'
    return line
