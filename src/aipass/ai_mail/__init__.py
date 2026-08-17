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

__all__ = ["FEED_PATH", "feed_path"]


def feed_path() -> "Path":
    """Absolute path to the notification feed BAUD's bell and @api's /v1/feed read.

    ``<repo root>/.aipass/notifications.jsonl`` — see the Notification Feed
    contract in this branch's README for the line schema and the trim policy
    that makes positional cursors go stale.
    """
    from aipass.ai_mail.apps.handlers.notify import feed_path as _feed_path

    return _feed_path()


def __getattr__(name: str) -> Any:
    """Resolve FEED_PATH without importing notify at package import time."""
    if name == "FEED_PATH":
        from aipass.ai_mail.apps.handlers.notify import FEED_PATH

        return FEED_PATH
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
