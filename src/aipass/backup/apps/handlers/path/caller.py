# =================== AIPass ====================
# Name: caller.py
# Description: Caller-CWD path resolution — relative paths resolve where the user is
# Version: 1.2.0
# Created: 2026-08-08
# Modified: 2026-11-15
# =============================================

"""Caller-CWD path resolution handler, and the fence on who may delete from a backup store."""

# Under drone, Path.cwd() is backup's own branch dir; drone exports AIPASS_CALLER_CWD, where the user typed.

import os
from pathlib import Path

from aipass.prax import logger

from ..audit import trail

#: The seat that owns every backup store: besides the verified admin, the only caller that deletes from one.
STORE_SEAT = "@backup"


def caller_cwd() -> Path:
    """Return the directory the user invoked the command from."""
    caller = os.environ.get("AIPASS_CALLER_CWD")
    if not caller:
        raise RuntimeError(
            "AIPASS_CALLER_CWD is not set, so a relative path has no caller directory: "
            "run through drone, or pass an absolute path"
        )
    return Path(caller)


def resolve_caller_path(target: str | Path) -> Path:
    """Resolve a user-supplied path against the CALLER's directory."""
    path = Path(target)
    if path.is_absolute():
        resolved = path.resolve()
    else:
        resolved = (caller_cwd() / path).resolve()
    trail.log_operation(
        "resolve_caller_path",
        {"given": str(target), "resolved": str(resolved)},
    )
    return resolved


def verified_caller() -> tuple[str, bool]:
    """Return (caller, is_admin) from @ai_mail's verified-caller rail; caller is "" when unprovable.

    Imported per call, so a dark rail fails only the gated verbs, and fails them closed: it raises.
    """
    from aipass.ai_mail import is_verified_admin_caller, resolve_verified_caller

    return resolve_verified_caller(), bool(is_verified_admin_caller())


def _record(operation: str, caller: str, target: Path, reason: str | None) -> None:
    """One trail row and one prax line per fence verdict, naming the caller."""
    who = caller or "<unverified>"
    trail.log_operation(operation, {"caller": who, "target": str(target), "refused": reason})
    if reason:
        logger.warning(f"[backup] {operation} REFUSED for {who}: {reason}")
    else:
        logger.info(f"[backup] {operation} allowed for {who}: {target}")


def store_delete_refusal(verb: str, project_root: Path) -> str | None:
    """Why the caller may not delete from *project_root*'s backup store with *verb*, or None when it may."""
    caller, admin = verified_caller()
    reason = None
    if not admin and caller != STORE_SEAT:
        who = caller or "an unverified caller"
        reason = f"{verb} deletes backup store entries: {STORE_SEAT}'s seat or the verified admin only, not {who}"
    _record(f"{verb.split()[0]}_fence", caller, project_root, reason)
    return reason
