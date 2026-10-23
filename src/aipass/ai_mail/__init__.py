"""AI Mail - Inter-branch messaging for AIPass.

Public surface. Reference: docs/dispatch_register_and_feed.md (the register is append-only; later records win).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Import-free type visibility; never executed at runtime.
    from pathlib import Path

__all__ = [
    "FEED_PATH",  # noqa: F822 - resolves via __getattr__ (PEP 562), not a module-level binding
    "feed_path",
    "outstanding_dispatches",
    "post_to_inbox_file",
    "register_path",
    "send_notification",
]


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


def post_to_inbox_file(inbox_file: "Path", email_data: dict) -> "tuple[bool, str, str]":
    """A guest's write into an inbox.json by path, under ai_mail's lock, with its feed event: (ok, error, id)."""
    from aipass.ai_mail.apps.handlers.email.delivery import deliver_to_inbox_file

    return deliver_to_inbox_file(inbox_file, email_data)


def send_notification(title: str, body: str, *, source: str, kind: str, extra: "dict | None" = None) -> bool:
    """One event on the notification feed from a foreign branch, named by source and kind: True when written."""
    from aipass.ai_mail.apps.handlers.notify import send_notification as _send

    return _send(title, body, source=source, kind=kind, extra=extra)


def __getattr__(name: str) -> Any:
    """Resolve FEED_PATH without importing notify at package import time."""
    if name == "FEED_PATH":
        from aipass.ai_mail.apps.handlers.notify import FEED_PATH

        return FEED_PATH
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
