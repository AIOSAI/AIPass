# =================== AIPass ====================
# Name: verified_caller.py
# Description: Verified-Caller Rail for privilege-bearing decisions
# Version: 1.6.0
# Created: 2026-08-12
# Modified: 2026-10-17
# =============================================

"""
Verified-Caller Rail

A CLI flag is a claim, not a credential. Reference: docs/identity_and_boundaries.md
"""

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

from .branch_detection import find_branch_root, _CREDENTIAL_SOURCES

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")


# Senders that unlock a wake lane. test_verified_caller.py checks every `sender == "@x"` gate in wake.py is listed here.
PRIVILEGED_SENDERS: frozenset[str] = frozenset({"@daemon"})


def _normalize(address: Optional[str]) -> str:
    """Return `@lowercase` form of a branch address, or "" for empty input."""
    if not address:
        return ""
    return f"@{address.strip().lstrip('@').lower()}"


def resolve_verified_caller() -> str:
    """Resolve the branch address of the process that actually invoked us.

    "" when the caller cannot be proven: a normal answer, never an exception. Bare cwd is never a fallback.
    """
    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")

    # Evidence before claim: a CALLER_CWD in no branch disproves CALLER_BRANCH (at the repo root drone stamps 'aipass').
    # Unset cwd is no verdict. Only a credential source (not a directory-name "project") survives the contradiction.
    if caller_cwd and not find_branch_root(Path(caller_cwd)):
        if os.environ.get("AIPASS_CALLER_IDENTITY_SOURCE") not in _CREDENTIAL_SOURCES:
            return ""

    branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    if branch:
        return _normalize(branch)

    if caller_cwd:
        root = find_branch_root(Path(caller_cwd))
        if root:
            return _normalize(root.name)

    return ""


def sender_claim_refusal(claimed: Optional[str]) -> Optional[str]:
    """Return a refusal reason if `claimed` is privilege-bearing and unproven."""
    claim = _normalize(claimed)
    if claim not in PRIVILEGED_SENDERS:
        return None

    verified = resolve_verified_caller()
    if verified == claim:
        return None

    who = verified or "unverified caller (no AIPASS_CALLER_BRANCH, no passport at AIPASS_CALLER_CWD)"
    json_handler.log_operation("sender_claim_refused", {"claimed": claim, "verified": verified})
    logger.warning("[identity] REFUSED sender claim %s — verified caller is %s", claim, verified or "<unverified>")
    return (
        f"sender {claim} is privilege-bearing and cannot be claimed by {who}. "
        f"It unlocks a wake lane, so it must match the caller drone stamped. "
        f"Drop the flag to send as yourself."
    )


def resolve_wake_sender(claimed: Optional[str]) -> str:
    """Return the sender value a wake may be given."""
    return resolve_verified_caller() or _normalize(claimed)


ADMIN_HOLDER: str = "@devpulse"


def verify_admin_caller(
    key_path: Optional[Path] = None,
    registry_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Run the full 5-leg admin-grant check."""
    try:
        from aipass.devpulse.apps.modules.door_admin_grant import verify_admin_grant
    except ImportError as exc:
        logger.warning("[identity] admin lane dark — reference implementation unavailable: %s", exc)
        return False, f"admin lane dark: devpulse admin_grant reference unavailable ({exc})"

    kwargs = {}
    if key_path is not None:
        kwargs["key_path"] = key_path
    if registry_path is not None:
        kwargs["registry_path"] = registry_path

    verified, reason = verify_admin_grant(**kwargs)
    json_handler.log_operation("verify_admin_caller", {"verified": verified, "reason": reason})
    if verified:
        logger.info("[identity] admin grant VERIFIED for %s", ADMIN_HOLDER)
    else:
        logger.info("[identity] admin grant not granted: %s", reason)
    return verified, reason


def is_verified_admin_caller() -> bool:
    """True only when the caller IS the admin holder and all five legs pass.

    Not cached, so a revoked grant takes effect on the next call. A raising verifier propagates (refusal, not False).
    """
    if resolve_verified_caller() != ADMIN_HOLDER:
        return False
    verified, _reason = verify_admin_caller()
    return bool(verified)


if __name__ == "__main__":
    from aipass.cli.apps.modules import console

    console.print()
    console.print("[bold cyan]VERIFIED-CALLER RAIL[/bold cyan]")
    console.print("[dim]Identity that gates a privilege comes from the env, never from a CLI flag.[/dim]")
    console.print()
    console.print("[yellow]FUNCTIONS PROVIDED:[/yellow]")
    console.print("  - resolve_verified_caller() -> str  [dim](@branch, or empty when unprovable)[/dim]")
    console.print("  - sender_claim_refusal(claimed) -> str | None  [dim](reason, or None if allowed)[/dim]")
    console.print("  - resolve_wake_sender(claimed) -> str  [dim](verified caller, else the claim)[/dim]")
    console.print("  - verify_admin_caller() -> (bool, reason)  [dim](5-leg admin grant, devpulse reference)[/dim]")
    console.print()
    console.print("[yellow]RESOLUTION ORDER:[/yellow]")
    console.print("  1. AIPASS_CALLER_BRANCH  [dim](drone, from real process ancestry)[/dim]")
    console.print("  2. AIPASS_CALLER_CWD walked up to .trinity/passport.json")
    console.print("  3. nothing — bare cwd is NOT a fallback here")
    console.print()
    console.print("[yellow]PRIVILEGED SENDERS:[/yellow]")
    for _addr in sorted(PRIVILEGED_SENDERS):
        console.print(f"  - {_addr}")
    console.print()
    console.print("[yellow]LIVE RESOLUTION:[/yellow]")
    console.print(f"  verified caller: {resolve_verified_caller() or '<unverified>'}")
    console.print()
