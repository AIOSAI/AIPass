# =================== AIPass ====================
# Name: feed.py
# Description: Watchdog Feed Handler — read completions off the push feed instead of polling for them
# Version: 1.1.0
# Created: 2026-08-21
# Modified: 2026-08-22
# =============================================

# Why this exists: baseline.py polls ~19 branches every 2s to SYNTHESISE an
# event that dispatch_monitor.py already knows and already writes. The producer
# was never missing — @ai_mail's notify.send_notification has been appending one
# line per dispatch to .aipass/notifications.jsonl the whole time (41 dispatch
# events on disk the day this was written). Detection by inference is replaced
# by detection by report.
#
# CURSOR CHOICE — the one thing that must not be copied from wire.py. That
# handler follows OUR append-only events file and holds a BYTE OFFSET. This feed
# is not append-only: notify._trim_feed rewrites it via os.replace at 400 lines,
# giving it a new inode and shifting every position. Its own docstring says
# readers must key on ts, not an offset. So the cursor here is a set of content
# digests over the lines currently in the file — trim-proof, restart-proof, and
# immune to a clock that steps backwards, at the cost of re-reading a <=400 line
# file whenever it actually changes.
#
# IDLE BY DESIGN: an unchanged (mtime, size) is one stat and an immediate
# return. A quiet system costs two syscalls per tick, not thirty-eight.

"""
Watchdog Feed Handler — the push side of completion detection.

Follows the shared notification feed that @ai_mail writes and BAUD's bell
reads, and reports the events this seat cares about. Nothing here writes to the
feed: it is another branch's file, consumed through their public
``feed_path()`` door rather than by restating the path.

Public surface:
  drain_feed(cursor_file, kinds=..., feed_file=None, seed_if_new=True)
      -> (records, cursor)
  format_feed_event(record) -> str
  feed_file() -> Path
  cursor_file_for(repo_root) -> Path
  FEED_KINDS, CURSOR_KEEP_DIGESTS

Each returned record is the feed's own line ({ts, kind, title, body, source})
plus a ``digest`` field — the idempotency key the feed itself does not carry.

See DPLAN-0314 for the design record and FPLAN-0451 for the build sequence.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.json import json_handler
from aipass import ai_mail as _ai_mail


# The kinds this seat wakes for. "mail" is deliberately excluded by default:
# every email the system sends writes one, including this branch's own, and a
# wake per email would be the noise that gets a wire muted. Callers can widen it.
FEED_KINDS = ("dispatch", "wake")

# How many line digests the cursor remembers. The feed keeps FEED_KEEP_LINES
# (200) after a trim and caps at FEED_MAX_LINES (400), so remembering 400 covers
# the whole file at its largest — a digest can never age out while its line is
# still on disk, which is what would resurface an already-delivered event.
CURSOR_KEEP_DIGESTS = 400

# Digest width. 16 hex chars of sha256 over the raw line: collision odds are
# negligible across a 400-line window, and the cursor file stays ~7KB.
_DIGEST_CHARS = 16

# The repo-root markers, used only to work out where the feed sits RELATIVE to
# its own root so that answer can be transplanted onto another tree. TWO
# markers, in this order, mirroring @ai_mail's find_repo_root (2026-08-23, the
# PR #739 fresh-checkout fix): the registry is runtime state and exists on no
# fresh checkout, so a walk that knows only the registry raises on every CI
# machine while passing on every machine with history. pyproject.toml is
# TRACKED and sits only at the repo root — the right answer was on the
# ancestor chain the whole time. The real retirement of both walks is a root
# door on @ai_mail's public surface; until then this pair must match theirs.
_ROOT_MARKERS = ("AIPASS_REGISTRY.json", "pyproject.toml")

# Named cursors, one per reader. See cursor_file_for.
#
# r4: there is exactly ONE reader now. DAEMON_CURSOR_NAME was deleted with the
# detection daemon that owned it. The stale devpulse_json/feed_daemon_cursor.json
# on disk is inert — nothing opens it — and is left where it is rather than
# deleted, because a file nobody reads costs nothing and a deletion nobody asked
# for costs a debugging session.
WIRE_CURSOR_NAME = "feed_cursor.json"


def feed_file(repo_root: Path | None = None) -> Path:
    """The notification feed's path, resolved through @ai_mail's public door.

    Never rebuild this expression locally. @api restated it once as their own
    constant and the duplicate is exactly what goes stale the day the feed
    moves — a bell showing nothing, with no error anywhere to explain it.

    ``repo_root`` re-roots that same answer onto another tree instead of
    hardcoding a second copy of it: the location is still learned from
    ``feed_path()``, only the base changes. This exists because a caller that
    honours an injected root for its OWN files while this function silently
    reached the live repo would read production state from inside a test —
    which is precisely what happened when the wire first called it.

    The transplant walks up from the owner's own answer to whichever parent
    carries the repo marker, so the relative shape is discovered rather than
    restated. Nothing here needs to know that the feed lives in ``.aipass/``.
    """
    resolved = _ai_mail.feed_path()
    if repo_root is None:
        return resolved

    for marker in _ROOT_MARKERS:
        for parent in resolved.parents:
            if (parent / marker).exists():
                return repo_root / resolved.relative_to(parent)

    # NO FALLBACK (Patrick's ruling, 2026-08-21). Returning the live path here
    # would hand a caller who explicitly asked for `repo_root` the PRODUCTION
    # feed instead — the exact defect fixed earlier the same evening, where two
    # tests read the real 216-line feed from inside tmp_path. A warning does not
    # prevent that; it just narrates it after the fact, into a log nobody reads
    # in time. The caller asked a question this function cannot answer, so it
    # says so and stops.
    raise RuntimeError(
        f"cannot re-root the notification feed onto {repo_root}: none of {_ROOT_MARKERS} "
        f"found above {resolved}, so its position relative to a repo root is unknown. "
        f"Pass feed_file_path explicitly, or omit repo_root to use the live feed deliberately."
    )


def cursor_file_for(repo_root: Path, name: str = WIRE_CURSOR_NAME) -> Path:
    """Where a reader remembers which feed lines it has already delivered.

    ``name`` survives r4 with one reader left, and it is not vestigial: it is
    the thing that stops a second reader from silently sharing this one. Two
    readers on one cursor steal each other's events — whichever drains first
    marks the line seen and the other never sees it at all. That failure is
    total and completely silent, so the parameter stays as the door a future
    reader has to walk through to get its own cursor.
    """
    return repo_root.joinpath("src", "aipass", "devpulse", "devpulse_json", name)


def _digest(raw_line: str) -> str:
    """Content key for one feed line — the idempotency key the feed omits.

    Keyed on the raw text rather than parsed fields so that two events which
    genuinely differ only in whitespace still hash apart, and so a line whose
    body is later re-rendered is correctly treated as a new event.
    """
    return hashlib.sha256(raw_line.encode("utf-8", errors="replace")).hexdigest()[:_DIGEST_CHARS]


def _read_cursor(cursor_file: Path) -> dict:
    """Load the delivery cursor. An unreadable cursor replays, never wedges.

    Duplicates over silence, the same doctrine wire.py holds: a replayed wake is
    noise a human dismisses, a dropped one is the failure this whole module
    exists to end. ``seeded`` distinguishes "we have never looked at this feed"
    from "we have looked and it was empty" — the first must not dump the entire
    backlog as if it were news.
    """
    try:
        data = json.loads(cursor_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # First run for this reader. Expected exactly once, so debug — a
        # warning on the happy path spends the signal budget teaching readers
        # to skim past it.
        logger.debug("[watchdog.feed] no cursor at %s — first drain for this reader", cursor_file)
        return {"seen": [], "seeded": False}
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("[watchdog.feed] cursor unreadable %s — replaying: %s", cursor_file, exc)
        return {"seen": [], "seeded": False}

    seen = data.get("seen")
    if not isinstance(seen, list):
        logger.warning("[watchdog.feed] cursor has no usable digest list — replaying")
        return {"seen": [], "seeded": False}

    return {
        "seen": [d for d in seen if isinstance(d, str)],
        "seeded": bool(data.get("seeded")),
        "stat": data.get("stat"),
    }


def _write_cursor(cursor_file: Path, seen: list[str], stat_key: list | None) -> None:
    """Persist the cursor atomically (tmp + replace).

    A torn cursor is survivable — it reads as unreadable and replays — but two
    lines of atomicity make that path unnecessary.
    """
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
    """(mtime_ns, size) — the cheap "did anything change" probe.

    This is the whole idle story: when it matches the cursor's copy there is
    nothing to read, and the tick costs one stat.
    """
    try:
        st = path.stat()
    except OSError as exc:
        # No feed yet, or it is momentarily unreadable. Both are answered the
        # same way (nothing to deliver) but neither may pass unrecorded — a
        # feed that is permanently unstat-able is a dead wake lane wearing the
        # face of a quiet one.
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

    Args:
        cursor_file: Where delivery state is remembered.
        kinds: Feed kinds to report. Others are still recorded as seen, so a
            muted kind never resurfaces later as a backlog.
        feed_file_path: Override the feed location (tests).
        seed_if_new: On a first-ever drain, absorb the existing feed silently
            instead of delivering its whole backlog as fresh news. There is no
            honest way to know what a previous session already saw.
        repo_root: Re-root the feed onto this tree (tests, alternate checkouts).
            Ignored when ``feed_file_path`` is given.
        state: The cursor returned by the previous call. Pass it in a follow
            loop: without it every tick re-reads and re-parses the cursor file,
            which makes the idle path two reads instead of the one stat this
            handler claims. Omit it for a one-shot drain.

    Returns:
        (records, cursor) — each record is the feed line plus ``digest``.
        ``cursor`` is the state to hand back on the next call.

    Raises:
        RuntimeError: via ``feed_file`` when ``repo_root`` is given but the feed
            cannot be located relative to a repo marker. A missing feed, an
            unreadable feed and a corrupt line are NOT errors — those are real
            states with defined answers, and each is logged. The difference is
            whether the caller asked something answerable.
    """
    path = feed_file_path if feed_file_path is not None else feed_file(repo_root)
    cursor = state if state is not None else _read_cursor(cursor_file)

    stat_key = _stat_key(path)
    if stat_key is None:
        # No feed yet. Nothing to deliver is a real answer, not an error — the
        # file is created by the first notification anyone sends.
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
            # Step over junk loudly rather than wedging delivery on it forever.
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
    """Render one feed event as a single wire line.

    Deliberately NOT baseline.format_completion: that formatter renders a
    lock-transition record (branch/subject/age/bounce) and this is a reported
    event with a different shape. Forcing one into the other is how a field
    ends up quietly labelled as something it is not.
    """
    kind = str(record.get("kind") or "?")
    source = str(record.get("source") or "?").lstrip("@")
    title = " ".join(str(record.get("title") or "?").split()).replace('"', "'")
    body = " ".join(str(record.get("body") or "").split()).replace('"', "'")
    line = f'{kind.upper()} @{source} title="{title}"'
    if body:
        line += f' detail="{body}"'
    return line
