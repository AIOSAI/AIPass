# =================== AIPass ====================
# Name: caller_gate.py
# Description: Caller Gate Handler: who may name another branch on a verb that writes its memory
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""A seat writes its own branch; @memory's seat and the verified admin (ai_mail's rail) may name another."""

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

MODULE_NAME = "caller_gate"
MEMORY_SEAT = "@memory"


def verified_caller() -> tuple[str, bool]:
    """``(caller, is_admin)`` from the rail; "" when unprovable. Imported per call: a dark rail fails only here."""
    from aipass.ai_mail.apps.modules import door_verified_caller as rail

    return rail.resolve_verified_caller(), bool(rail.is_verified_admin_caller())


def _address(name: str) -> str:
    return f"@{name.strip().lstrip('@').lower()}"


def other_branch_refusal(verb: str, target: str | None, *, unverified_passes: bool = False) -> str | None:
    """Why the caller may not run *verb* against *target* (None = the fleet), or None when it may.

    *unverified_passes* is for rollover run only: @hooks' PreCompact shells drone from the repo root,
    where an interactive session verifies as nobody.
    """
    wanted = _address(target) if target else None
    try:
        caller, admin = verified_caller()
        rail_down = None
    except Exception as exc:  # fail closed: a dark rail is a refusal, never a pass
        caller, admin, rail_down = "", False, f"{type(exc).__name__}: {exc}"

    what = f"{wanted}'s .trinity memory" if wanted else "every branch's .trinity memory"
    who = caller or "an unverified caller"
    reason = None
    if rail_down:
        reason = f"{verb} writes {what}, and the verified-caller rail is unavailable ({rail_down}) - nothing written"
    elif (caller and caller == wanted) or caller == MEMORY_SEAT or admin or (not caller and unverified_passes):
        reason = None
    elif wanted:
        reason = f"{verb} writes {what}: its own seat, {MEMORY_SEAT} or the verified admin only, not {who} - "
        reason += f"run it from inside {wanted}'s own directory"
    else:
        reason = f"{verb} writes {what}: {MEMORY_SEAT} or the verified admin only, not {who} - "
        reason += "mail @devpulse, whose lane the fleet push is"

    json_handler.log_operation(
        "caller_gate",
        {"verb": verb, "target": wanted or "fleet", "caller": who, "admin": admin, "refused": reason},
        module_name=MODULE_NAME,
    )
    if reason:
        logger.warning(f"[caller_gate] {verb} REFUSED for {who}: {reason}")
    return reason
