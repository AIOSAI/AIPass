"""AI Mail - Inter-branch messaging for AIPass.

Public surface. Reference: docs/dispatch_register_and_feed.md (the register is append-only; later records win).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Import-free type visibility; never executed at runtime.
    from pathlib import Path

__all__ = ["FEED_PATH", "feed_path", "outstanding_dispatches", "register_path"]  # noqa: F822 - FEED_PATH resolves via __getattr__ (PEP 562), not a module-level binding


def feed_path() -> "Path":
    """Absolute path to the notification feed BAUD's bell and @api's /v1/feed read."""
    from aipass.ai_mail.apps.handlers.notify import feed_path as _feed_path

    return _feed_path()


def register_path() -> "Path":
    """Absolute path to the dispatch register."""
    from aipass.ai_mail.apps.handlers.dispatch.register import register_file

    return register_file()


def outstanding_dispatches(repo_root: "Path | None" = None) -> "list[dict]":
    """Every dispatch still open, newest first, with ``overdue`` and ``monitor_alive``."""
    from aipass.ai_mail.apps.handlers.dispatch.register import outstanding

    return outstanding(repo_root)


def __getattr__(name: str) -> Any:
    """Resolve FEED_PATH without importing notify at package import time."""
    if name == "FEED_PATH":
        from aipass.ai_mail.apps.handlers.notify import FEED_PATH

        return FEED_PATH
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
