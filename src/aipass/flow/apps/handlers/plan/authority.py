# =================== AIPass ====================
# Name: authority.py
# Description: Who may create, close, restore or repair plans: owners, flow's own seat, the verified admin
# Version: 1.1.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Every gate reads the caller from @ai_mail's verified-caller rail and records each refusal with it."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.ai_mail import is_verified_admin_caller, resolve_verified_caller

from aipass.flow.apps.handlers.json import json_handler

MODULE_NAME = "authority"

PASSPORT = Path(".trinity") / "passport.json"
FLOW_SEAT = "@flow"
# Identity, config, VCS, provider and archive trees: no plan is ever filed inside one, whoever asks.
FORBIDDEN_DIRS = frozenset({".trinity", ".aipass", ".git", ".codex", ".agents", ".archive"})


def caller_address() -> str:
    """The verified caller as ``@branch``, or "" when the rail cannot prove one."""
    return resolve_verified_caller()


def holding_branch(path: Path) -> str:
    """``@branch_name`` from the nearest passport at or above ``path``; "" when none, relative or unnamed.

    The passport's branch_name, not the directory name: it is what drone stamps as the caller.
    An unreadable passport raises: the gate refuses rather than guess a holder.
    """
    if not path.is_absolute():
        return ""
    for directory in (path, *path.parents):
        passport = directory / PASSPORT
        if passport.is_file():
            name = json.loads(passport.read_text(encoding="utf-8")).get("branch_info", {}).get("branch_name")
            return f"@{name.lower()}" if isinstance(name, str) and name else ""
    return ""


def _admin_seat() -> bool:
    """The rail's five-leg admin verdict; a raising verifier refuses."""
    try:
        return bool(is_verified_admin_caller())
    except Exception as exc:
        logger.warning(f"[{MODULE_NAME}] admin verification raised, refusing: {exc}")
        return False


def _refused(operation: str, record: Dict[str, Any], text: str) -> str:
    """Record one refusal with its caller and hand back the text."""
    json_handler.log_operation(operation, record)
    logger.warning(f"[{MODULE_NAME}] REFUSED {operation} by {record.get('caller') or '<unverified>'}")
    return text


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
    by_creator = f" ({creator})" if creator else ", not recorded on this plan"
    return _refused(
        f"plan_{verb}_refused",
        {"plan_file": str(plan_file), "caller": caller, "holder": holder, "created_by": creator},
        f"Refused: {plan_file.name} sits in {holder or 'no branch'}. A plan is {verb}d by the branch "
        f"that holds it, the citizen that created it{by_creator}, or the verified admin seat; "
        f"you are {caller or 'an unverified caller'}. Nothing was moved or written. "
        f'Next: drone @ai_mail email {owner} "{verb} {plan_file.stem}" "<why>"',
    )


def create_refusal(target_dir: Path) -> Optional[str]:
    """None when a plan may be filed in ``target_dir``: inside any branch, or anywhere for the admin seat."""
    resolved = target_dir.resolve()
    caller = caller_address()
    record = {"target": str(resolved), "caller": caller}
    forbidden = FORBIDDEN_DIRS.intersection(resolved.parts)
    if forbidden:
        return _refused(
            "plan_create_refused",
            record,
            f"Refused: {resolved} is inside {sorted(forbidden)[0]}/, where no plan is filed for any caller. "
            "Nothing was written. Next: create it in the branch directory itself.",
        )
    if holding_branch(resolved) or _admin_seat():
        return None
    return _refused(
        "plan_create_refused",
        record,
        f"Refused: {resolved} is outside every branch; only the verified admin seat files a plan there, "
        f"and you are {caller or 'an unverified caller'}. Nothing was written. "
        f'Next: create it inside a branch, or drone @ai_mail email @devpulse "plan at {resolved}" "<why>"',
    )


def seat_refusal(operation: str) -> Optional[str]:
    """None when the caller is flow's own seat or the verified admin; a repair verb's real run is theirs."""
    caller = caller_address()
    if caller == FLOW_SEAT or _admin_seat():
        return None
    return _refused(
        f"{operation}_refused",
        {"caller": caller},
        f"Refused: {operation} rewrites every branch's plan rows; its real run is for {FLOW_SEAT} or the "
        f"verified admin seat, and you are {caller or 'an unverified caller'}. Nothing was written. "
        f'Next: drone @ai_mail email {FLOW_SEAT} "{operation}" "<why>"',
    )
