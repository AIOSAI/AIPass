# =================== AIPass ====================
# Name: dispatches.py
# Description: Watchdog seat attribution — which completions are THIS seat's, and what is still out
# Version: 2.0.0
# Created: 2026-08-22
# Modified: 2026-10-17
# =============================================

"""Watchdog seat attribution — whose dispatch was that, and what is still out."""

# Never fold @ai_mail's register here, it owns the rule; registry.py beside this is unrelated.

from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.owner.guard import owner_address as _owner_address
from aipass import ai_mail as _ai_mail


class RegisterUnavailable(RuntimeError):
    """This seat's identity or the register could not be resolved."""


def seat_email(repo_root: Path | None = None) -> str:
    """The address whose dispatches this seat owns — ``@devpulse`` here."""
    # owner_address() is soft for its refusal message; arming must not guess, so None turns hard.
    address: Any = _owner_address(start_path=repo_root)
    if not address:
        raise RegisterUnavailable(
            "no sealed owner for this project — cannot decide which dispatches are this seat's. "
            "Run: aipass doctor --fix"
        )
    return _normalise(address)


def _normalise(address: str) -> str:
    """One spelling for an address, so ``devpulse`` and ``@DevPulse`` compare equal."""
    return f"@{str(address).lstrip('@').lower()}"


def is_mine(record: dict, seat: str) -> bool:
    """True when this completion belongs to a dispatch THIS seat sent."""
    sender = record.get("sender")
    if not isinstance(sender, str) or not sender:
        return False
    return _normalise(sender) == _normalise(seat)


def outstanding(repo_root: Path | None = None) -> list[dict]:
    """Every dispatch still open, newest first, each carrying an ``overdue`` bool."""
    return list(_ai_mail.outstanding_dispatches(repo_root))


def overdue(repo_root: Path | None = None) -> list[dict]:
    """The outstanding dispatches that are past their expected_by.

    Not proof the monitor died: a retry runs on past the FIRST expected_by.
    """
    late = [entry for entry in outstanding(repo_root) if entry.get("overdue")]
    if late:
        logger.info("[watchdog.dispatches] %s dispatch(es) past the hard timeout, monitor state unknown", len(late))
        json_handler.log_operation("dispatches_overdue", {"count": len(late)})
    return late
