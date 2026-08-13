# =================== AIPass ====================
# Name: verified_caller.py
# Description: Verified-Caller Rail for privilege-bearing decisions
# Version: 1.2.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""
Verified-Caller Rail

Identity that GATES something may only come from the environment drone stamps
from real process ancestry (``AIPASS_CALLER_BRANCH``, falling back to a passport
walk up ``AIPASS_CALLER_CWD``). A CLI flag is a claim, not a credential.

Why this exists: ``--from`` (dispatch send) and ``--sender`` (manual wake) both
land on ``wake_branch(sender=...)``, and ``sender == "@daemon"`` unlocks the
manager wake lane. Until this rail, any citizen could run
``dispatch @manager --from @daemon`` and wake a manager (found by a @devpulse
read-only scout, DPLAN-0288, traced not executed).

The split this module draws:

- **claimed identity** — what the caller typed. Still authors the mail; it is
  display/routing metadata and stays as permissive as it ever was.
- **verified identity** — who the rail can prove is calling. The only thing a
  privilege may read.

Deliberately NOT a fallback to ``Path.cwd()``: drone runs a routed module with
``cwd=<target branch>`` and a dispatched agent runs with ``cwd=<its own tree>``,
so this process's own directory says nothing about who called. Unprovable
returns "" and a privileged claim on "" is refused — fail closed.

Scope: this is the CLI boundary. Direct in-process callers of ``wake_branch``
(e.g. @daemon's ``run.py``) never pass through here; that trust model is the
import boundary, not this one.
"""

# =============================================
# IMPORTS
# =============================================
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

from .branch_detection import find_branch_root

if sys.platform == "win32":
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        _reconfigure = getattr(_stream, "reconfigure", None)
        if _reconfigure is not None:
            _reconfigure(encoding="utf-8", errors="replace")

# =============================================
# CONSTANTS
# =============================================

# Sender values that unlock a wake lane rather than just addressing a bounce.
# Kept here, at the boundary that enforces them, because wake_branch itself
# cannot: its in-process callers have no caller env to check against and are
# trusted by import. test_verified_caller.py scans wake.py for `sender == "@x"`
# gates and fails if one is missing from this set — Phase 4's admin identity
# lands in both places or not at all.
PRIVILEGED_SENDERS: frozenset[str] = frozenset({"@daemon"})


def _normalize(address: Optional[str]) -> str:
    """Return `@lowercase` form of a branch address, or "" for empty input."""
    if not address:
        return ""
    return f"@{address.strip().lstrip('@').lower()}"


def resolve_verified_caller() -> str:
    """Resolve the branch address of the process that actually invoked us.

    Two legs, in order:
      1. ``AIPASS_CALLER_BRANCH`` — drone's assigned identity, stamped from real
         process ancestry (router_handler).
      2. ``AIPASS_CALLER_CWD`` walked up to a ``.trinity/passport.json``.

    Returns:
        str: ``@branch``, or "" when the caller cannot be proven. "" is a
        normal answer (direct invocation, no drone), never an exception —
        callers decide what an unproven caller may do.
    """
    branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    if branch:
        return _normalize(branch)

    caller_cwd = os.environ.get("AIPASS_CALLER_CWD", "")
    if caller_cwd:
        root = find_branch_root(Path(caller_cwd))
        if root:
            return _normalize(root.name)

    return ""


def sender_claim_refusal(claimed: Optional[str]) -> Optional[str]:
    """Return a refusal reason if `claimed` is privilege-bearing and unproven.

    A claim that gates nothing is never refused — ``--from @spawn`` from any
    seat stays legal, because the value only rides on the mail. A claim that
    DOES gate something must equal the verified caller.

    Args:
        claimed: The sender address the caller supplied, or None.

    Returns:
        Optional[str]: Human-readable reason naming both identities, or None
        when the claim is allowed.
    """
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
    """Return the sender value a wake may be given.

    The verified caller when there is one; otherwise the claim, which
    :func:`sender_claim_refusal` has already guaranteed is not
    privilege-bearing. So the value reaching ``wake_branch`` is either proven
    or harmless — never an unproven privileged string.

    Args:
        claimed: The sender address the caller supplied, or None.

    Returns:
        str: Address for bounce mail and wake-back. "" stays "" — that is
        wake-back's chain terminator, not an identity to invent.
    """
    return resolve_verified_caller() or _normalize(claimed)


ADMIN_HOLDER: str = "@devpulse"


def verify_admin_caller(
    key_path: Optional[Path] = None,
    registry_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Run the full 5-leg admin-grant check (FPLAN-0401 THE CONTRACT).

    Delegates to @devpulse's reference implementation rather than mirroring it:
    the contract has one home, so a change to it cannot silently disagree with
    this lane. The legs are caller identity, registry-resolved cert path, cert
    content, HMAC-SHA256 signature, and the registry admin flag — all five, or
    nothing.

    Fail-closed at every edge: if the reference cannot be imported the lane is
    dark, not open. Nothing here reads or logs key material.

    Args:
        key_path: Override the signing-key path (tests only — production uses
            the reference's default, ``~/.aipass/admin_grant.key``).
        registry_path: Override the registry path (tests only).

    Returns:
        Tuple[bool, str]: (verified, reason). The reason names the failed leg
        so a refusal can be read without a debugger.
    """
    try:
        # Cross-branch handler import, authorized by @devpulse in the FPLAN-0401
        # Phase 4 dispatch: "lazy-import it — one implementation, no drift".
        # Their modules/ entry point re-exports this same function object, but
        # importing the handler keeps the dependency tight (no CLI/help layer
        # pulled in at verification time). Both shapes need a bypass entry;
        # this is the narrower one. Bypassed: handlers (cross-branch import).
        from aipass.devpulse.apps.handlers.owner.admin_grant import verify_admin_grant
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

    The single boolean the cross-project bridge consumes. Two gates, in order:

    1. The verified-caller rail must say this process IS the holder. Every other
       citizen short-circuits here and does zero file I/O — noise control, NOT
       security (leg 1 inside the reference decides that, independently).
    2. The 5-leg grant must verify. Any raise is a refusal: the bridge fails
       closed, never open.

    Deliberately NOT cached. A revoked grant has to take effect on the next
    call; a per-process cache would keep a torn-up grant alive until restart,
    which is failing open.

    Returns:
        True if this caller may cross project boundaries, False otherwise.
    """
    if resolve_verified_caller() != ADMIN_HOLDER:
        return False
    try:
        verified, _reason = verify_admin_caller()
    except Exception as exc:
        logger.warning("[identity] admin verification failed unexpectedly: %s", exc)
        return False
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
