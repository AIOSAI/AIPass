# =================== AIPass ====================
# Name: seat_gate.py
# Description: Seat gate — a real run of a lane that rewrites another branch is spawn's or the admin's
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Seat gate for the write lanes that move, rename, rewrite or remove another citizen's files.

A real run is for this branch's own verified seat or the verified admin seat; a preview stays open to every seat.
"""

from aipass.prax import logger

from aipass.ai_mail import is_verified_admin_caller, resolve_verified_caller
from aipass.spawn.apps.handlers import MY_BRANCH
from aipass.spawn.apps.handlers.registry import ADMIN_BRANCH
from aipass.spawn.apps.handlers.json import json_handler

PREVIEW_NOTE = (
    f"A real run is @{MY_BRANCH}'s or the verified admin seat's; any other seat mails "
    f"@{MY_BRANCH} or @{ADMIN_BRANCH} the branch and why"
)


def _is_admin() -> bool:
    """The ai_mail rail's five-leg admin verdict; a raising verifier refuses."""
    try:
        return bool(is_verified_admin_caller())
    except Exception as exc:
        logger.warning("[seat_gate] admin verification raised, refusing: %s", exc)
        return False


def seat_refusal(verb: str, target: str) -> str | None:
    """None when the caller may run *verb* for real; otherwise the refusal, logged and recorded with the caller."""
    caller = resolve_verified_caller() or "unknown"
    if caller == f"@{MY_BRANCH}" or _is_admin():
        return None
    msg = (
        f"{verb} runs for real from @{MY_BRANCH} or the verified admin seat only (caller {caller}); "
        f"mail @{MY_BRANCH} or @{ADMIN_BRANCH} the branch and why"
    )
    logger.warning("[seat_gate] refused %s %s: caller %s", verb, target, caller)
    json_handler.log_operation("write_refused", data={"verb": verb, "target": target, "caller": caller})
    return msg
