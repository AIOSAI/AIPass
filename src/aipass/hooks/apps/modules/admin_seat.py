# =================== AIPass ====================
# Name: admin_seat.py
# Version: 1.0.0
# Description: The verified admin-seat exemption, read once for every gate that honours it
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Answers one question for every security gate: is this session the admin seat?

Extracted from ``handlers/security/edit_gate.py`` on 2026-09-01, unchanged in
behaviour, when a second gate (``testwrite_gate``) needed the same answer. The
reason is the one edit_gate's own docstring already gave for consuming
@ai_mail's rail rather than mirroring it: a contract with two readings can
disagree with itself, and a security exemption that disagrees with itself opens
on the weaker reading. One home, two callers.

THE ONE THING A HOOK MUST SUPPLY. @ai_mail's rail reads identity from the env
drone's router stamps (``AIPASS_CALLER_BRANCH`` / ``AIPASS_CALLER_CWD``), and a
PreToolUse hook is not drone-invoked: neither variable exists in the hook
process, so the rail would answer "unprovable" for devpulse and every other seat
alike and the exemption would never open. What the hook DOES have is the
platform's own record of the session directory, handed to it in the hook payload
— the same species of evidence drone stamps, from the same kind of source: the
process that launched the session, not the agent running inside it. So the
caller cwd is stamped here and the rail does the rest (the passport walk, the
registry-resolved certificate, the HMAC, the admin flag). An existing stamp is
never overwritten — a drone-invoked caller keeps the identity drone gave it.

Deliberately NOT a name check. :data:`ADMIN_SEAT` never decides anything: a
session standing in a directory called devpulse with no valid grant on the
machine is refused, which is the defect ``drone rm`` fell to.

Residual, stated rather than discovered: leg 1 resolves through the session
directory, so a session whose cwd is devpulse's tree AND a validly signed grant
on this machine together satisfy it. That is the grant's own stated threat model
— every agent here shares one OS user, and the signature buys tamper-EVIDENCE,
not attack-proofing (admin_grant.py, "Security note").

Fails closed at every edge: an unimportable rail, a raise, or an unprovable
caller all return False.
"""

import importlib
import os

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# The one seat that reaches outwards. Patrick, 2026-08-30, compassed as devpulse
# entry 322: "It is only you who can reach outwards. Nobody else."
# Named here for the log line only — WHO is decided by the verified rail below,
# never by this string matching a directory.
ADMIN_SEAT = "devpulse"

_RAIL = "aipass.ai_mail.apps.handlers.users.verified_caller"


def is_admin_seat(cwd: str) -> bool:
    """True only when the 5-leg admin grant verifies for this session.

    Args:
        cwd: The session working directory from the hook payload.

    Returns:
        True when the grant verifies, False on every doubt.
    """
    return _verified(cwd)


def _verified(cwd: str) -> bool:
    """Stamp the caller cwd, ask @ai_mail's rail, and never leave the stamp behind."""
    try:
        vc = importlib.import_module(_RAIL)
    except Exception as exc:
        logger.warning("[HOOKS] admin_seat: admin lane dark — verified-caller rail unavailable: %s", exc)
        return False

    stamped = not os.environ.get("AIPASS_CALLER_CWD") and bool(cwd)
    if stamped:
        os.environ["AIPASS_CALLER_CWD"] = cwd
    try:
        return bool(vc.is_verified_admin_caller())
    except Exception as exc:
        logger.warning("[HOOKS] admin_seat: admin verification raised (refusing): %s", exc)
        return False
    finally:
        if stamped:
            os.environ.pop("AIPASS_CALLER_CWD", None)


def print_introspection() -> None:
    """Print module structure for drone routing.

    Reports the CONTRACT, never a live verdict: answering "are you admin right
    now" from a CLI would stamp a caller cwd from whichever directory the
    operator happened to stand in, which is the name-check this module exists
    to refuse.
    """
    CONSOLE.print(f"[bold cyan]admin_seat[/bold cyan] — is this session the admin seat (@{ADMIN_SEAT})?")
    CONSOLE.print(f"[dim]Consumes {_RAIL}.is_verified_admin_caller — the 5-leg grant.[/dim]")
    CONSOLE.print("[dim]Consumed by handlers/security/edit_gate.py and handlers/security/testwrite_gate.py.[/dim]")
    CONSOLE.print("[yellow]Fails closed:[/yellow] an unimportable rail, a raise, or an unprovable caller all refuse.")
