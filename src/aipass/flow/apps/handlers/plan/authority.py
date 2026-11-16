# =================== AIPass ====================
# Name: authority.py
# Description: Who may close or reopen a plan: its branch, its creator, or the verified admin seat
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Close and restore answer to a plan's branch, its ``created_by`` citizen, or the verified admin seat."""

from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.ai_mail.apps.modules.door_verified_caller import is_verified_admin_caller, resolve_verified_caller

from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "authority"

PASSPORT = Path(".trinity") / "passport.json"


def caller_address() -> str:
    """The verified caller as ``@branch``, or "" when the rail cannot prove one."""
    return resolve_verified_caller()


def holding_branch(path: Path) -> str:
    """``@name`` of the nearest directory at or above ``path`` carrying a passport; "" when none (or relative)."""
    if not path.is_absolute():
        return ""
    for directory in (path, *path.parents):
        if (directory / PASSPORT).is_file():
            return f"@{directory.name.lower()}"
    return ""


def _admin_seat() -> bool:
    """The rail's five-leg admin verdict; a raising verifier refuses."""
    try:
        return bool(is_verified_admin_caller())
    except Exception as exc:
        logger.warning(f"[{MODULE_NAME}] admin verification raised, refusing: {exc}")
        return False


def authority_refusal(plan_file: Path, plan_info: Dict[str, Any], verb: str = "close") -> Optional[str]:
    """None when the caller may ``verb`` this plan, else the refusal text with the next step."""
    caller = caller_address()
    holder = holding_branch(plan_file)
    creator = plan_info.get("created_by", "")
    if caller and caller in (holder, creator):
        return None
    if _admin_seat():
        return None

    owner = holder or creator or "@devpulse"
    json_handler.log_operation(
        f"plan_{verb}_refused",
        {"plan_file": str(plan_file), "caller": caller, "holder": holder, "created_by": creator},
    )
    logger.warning(f"[{MODULE_NAME}] REFUSED {verb} of {plan_file.name} by {caller or '<unverified>'}")
    by_creator = f" ({creator})" if creator else ", not recorded on this plan"
    return (
        f"Refused: {plan_file.name} sits in {holder or 'no branch'}. A plan is {verb}d by the branch "
        f"that holds it, the citizen that created it{by_creator}, or the verified admin seat; "
        f"you are {caller or 'an unverified caller'}. Nothing was moved or written. "
        f'Next: drone @ai_mail email {owner} "{verb} {plan_file.stem}" "<why>"'
    )
