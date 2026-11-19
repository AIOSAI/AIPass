"""AI Mail - Inter-branch messaging for AIPass.

Public surface. Reference: docs/dispatch_register_and_feed.md (the register is append-only; later records win).
"""

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # Import-free type visibility; never executed at runtime.
    from pathlib import Path

_HANDLERS = "aipass.ai_mail.apps.handlers"
_CALLER = f"{_HANDLERS}.users.verified_caller"
_WAKE = f"{_HANDLERS}.dispatch.wake"
_POINTER = f"{_HANDLERS}.dispatch.session_pointer"
_GRANT = f"{_HANDLERS}.dispatch.grant"

# Each name's real home: the door loads that one module on access, nothing more.
_HOMES = {
    "FEED_PATH": f"{_HANDLERS}.notify",
    "is_verified_admin_caller": _CALLER,
    "resolve_verified_caller": _CALLER,
    "wake_branch": _WAKE,
    "is_wake_blocked": _WAKE,
    "resolve_resume_target": _POINTER,
    "write_pointer": _POINTER,
    "read_pointer": _POINTER,
    "mint_session_id": _POINTER,
    "transcript_dir": _POINTER,
    "codex_thread_file": _POINTER,
    "opencode_db": _POINTER,
    "CLAUDE": _POINTER,
    "CODEX": _POINTER,
    "OPENCODE": _POINTER,
    "granted": _GRANT,
    "open_grants": _GRANT,
    "GRANT_KEY": _GRANT,
    "deliver_email_to_branch": f"{_HANDLERS}.email.delivery",
}

__all__ = [
    "feed_path",
    "mail_kind",
    "outstanding_dispatches",
    "post_to_inbox_file",
    "register_path",
    "send_notification",
    *_HOMES,
]


def feed_path() -> "Path":
    """Absolute path to the notification feed BAUD's bell and @api's /v1/feed read."""
    return importlib.import_module(f"{_HANDLERS}.notify").feed_path()


def register_path() -> "Path":
    """Absolute path to the dispatch register."""
    return importlib.import_module(f"{_HANDLERS}.dispatch.register").register_file()


def outstanding_dispatches(repo_root: "Path | None" = None) -> "list[dict]":
    """Every dispatch still open, newest first, with ``overdue`` and ``monitor_alive``."""
    return importlib.import_module(f"{_HANDLERS}.dispatch.register").outstanding(repo_root)


def mail_kind(message: dict) -> str:
    """A stored inbox message's kind: medic, rounds, job_failed, notice or mail (docs/mail_kinds.md)."""
    return importlib.import_module(f"{_HANDLERS}.email.mail_kind").stored_kind(message)


def post_to_inbox_file(inbox_file: "Path", email_data: dict) -> "tuple[bool, str, str]":
    """A guest's write into an inbox.json by path, under ai_mail's lock, with its feed event: (ok, error, id)."""
    return importlib.import_module(f"{_HANDLERS}.email.delivery").deliver_to_inbox_file(inbox_file, email_data)


def send_notification(title: str, body: str, *, source: str, kind: str, extra: "dict | None" = None) -> bool:
    """One event on the notification feed from a foreign branch, named by source and kind: True when written."""
    notify = importlib.import_module(f"{_HANDLERS}.notify")
    return notify.send_notification(title, body, source=source, kind=kind, extra=extra)


def __getattr__(name: str) -> Any:
    """Hand out a door name from its home on each access; nothing under apps loads at package import."""
    if name not in _HOMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # Never cached on the package: a patch on the home attribute must reach every caller reading through here.
    return getattr(importlib.import_module(_HOMES[name]), name)


def __dir__() -> list:
    """Public names, whether or not they have been resolved yet."""
    return sorted(set(globals()) | set(__all__))
