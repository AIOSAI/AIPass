# =================== AIPass ====================
# Name: admin_seat.py
# Version: 1.1.3
# Description: The verified admin-seat exemption and the caller's name, read once for every gate
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Answers one question for every security gate: is this session the admin seat?

A hook is not drone-invoked, so it stamps AIPASS_CALLER_CWD for @ai_mail's verified rail; fails closed.
"""

import importlib
import json
import os
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# For the log line only: who is admin is decided by the verified rail, never by this string.
ADMIN_SEAT = "devpulse"

_RAIL = "aipass.ai_mail.apps.modules.door_verified_caller"


def is_admin_seat(cwd: str) -> bool:
    """True only when the 5-leg admin grant verifies for this session."""
    return _verified(cwd)


def caller_name(cwd: str) -> str | None:
    """The citizen a session belongs to, named by the passport above *cwd*, never by the path.

    For refusal text only: a name never decides who passes. Raises on an unreadable passport.
    """
    if not cwd:
        return None
    search = Path(cwd).resolve()
    home = Path.home().resolve()  # both sides resolved, or a symlinked home never stops the walk
    while search != home and search.parent != search:
        passport = search / ".trinity" / "passport.json"
        if passport.exists():
            data = json.loads(passport.read_text(encoding="utf-8"))
            name = data.get("branch_info", {}).get("branch_name") or data.get("identity", {}).get("name")
            return name if isinstance(name, str) and name else None
        search = search.parent
    return None


def seat_of(cwd: str) -> tuple[str | None, bool]:
    """(caller name, verified admin) for one session, for the gates that refuse by seat.

    An unreadable passport costs the name, never the decision.
    """
    try:
        name = caller_name(cwd)
    except (OSError, ValueError, AttributeError) as exc:
        logger.warning("[HOOKS] admin_seat: caller passport above %s unreadable, caller unnamed: %s", cwd, exc)
        name = None
    return name, is_admin_seat(cwd)


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
    # Every caller is a gate: a raising verifier fails closed, and the warning tells it from a no.
    except Exception as exc:
        logger.warning("[HOOKS] admin_seat: admin verification raised (refusing): %s", exc)
        return False
    finally:
        if stamped:
            os.environ.pop("AIPASS_CALLER_CWD", None)


def print_introspection() -> None:
    """Print module structure for drone routing.

    The contract, never a live verdict: a CLI answer would stamp whatever cwd the operator stands in.
    """
    CONSOLE.print(f"[bold cyan]admin_seat[/bold cyan] — is this session the admin seat (@{ADMIN_SEAT})?")
    CONSOLE.print(f"[dim]Consumes {_RAIL}.is_verified_admin_caller — the 5-leg grant.[/dim]")
    CONSOLE.print("[dim]Consumed by edit_gate, testwrite_gate, rm_gate and git_gate (handlers/security/).[/dim]")
    CONSOLE.print("[yellow]Fails closed:[/yellow] an unimportable rail, a raise, or an unprovable caller all refuse.")
