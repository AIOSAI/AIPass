"""AI Mail - Inter-branch messaging for AIPass.

Public surface. Everything else in this package is internal — importing from
``apps.handlers`` across a branch boundary is an encapsulation violation, and
seedgo flags it. Anything another citizen legitimately needs is exported here.

Why lazily: the notification feed lives in ``apps.handlers.notify``, which
pulls in prax's logger and the JSON handler. Binding those at package import
would make ``import aipass.ai_mail`` drag the logging stack into every
consumer, so the names resolve on first access via PEP 562.
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Import-free type visibility; never executed at runtime.
    from pathlib import Path

__all__ = ["FEED_PATH", "feed_path", "outstanding_dispatches", "register_path"]


def feed_path() -> "Path":
    """Absolute path to the notification feed BAUD's bell and @api's /v1/feed read.

    ``<repo root>/.aipass/notifications.jsonl`` — see the Notification Feed
    contract in this branch's README for the line schema and the trim policy
    that makes positional cursors go stale.
    """
    from aipass.ai_mail.apps.handlers.notify import feed_path as _feed_path

    return _feed_path()


def register_path() -> "Path":
    """Absolute path to the dispatch register (FPLAN-0452 P0).

    ``<repo root>/.aipass/dispatch_register.jsonl``. Requested by @devpulse for
    the same reason ``feed_path`` exists: a consumer that assumes the register
    sits beside the feed has duplicated this location, and a duplicate goes
    stale silently the day it moves.

    APPEND-ONLY, and a reader that does not know that will be wrong rather than
    broken. A dispatch is closed by a SECOND record carrying the same
    ``dispatch_id``; the first is never rewritten. Read forward and let later
    records win — take the first record per id and every dispatch ever made
    reads as outstanding forever. ``outstanding_dispatches()`` does exactly
    this, and is the reason to prefer it over parsing this file yourself.
    """
    from aipass.ai_mail.apps.handlers.dispatch.register import register_file

    return register_file()


def outstanding_dispatches(repo_root: "Path | None" = None) -> "list[dict]":
    """Every dispatch still open, newest first, each carrying an ``overdue`` bool.

    The register's reconstruction has ONE owner, and this is it. The rule that
    "later records win" is the whole append-only contract, and a second
    implementation of it in a consumer is a duplicated path's worse cousin —
    duplicated LOGIC, which fails silently and plausibly rather than loudly.

    ``overdue`` means the entry is past its ``expected_by`` with no completion
    record. Because ``expected_by`` comes from ``dispatch_monitor``'s own
    HARD_TIMEOUT — which a live monitor cannot legitimately overrun, since it
    kills the run at that mark and reports — an overdue entry means the MONITOR
    DIED. It is not "taking a while".

    Nothing runs to produce this. The staleness is a fact about a file, and
    this function is someone looking at it.

    Args:
        repo_root: Re-root onto another tree (a test, another project). Raises
                   RuntimeError rather than silently returning the live answer.
    """
    from aipass.ai_mail.apps.handlers.dispatch.register import outstanding

    return outstanding(repo_root)


def __getattr__(name: str) -> Any:
    """Resolve FEED_PATH without importing notify at package import time."""
    if name == "FEED_PATH":
        from aipass.ai_mail.apps.handlers.notify import FEED_PATH

        return FEED_PATH
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
