# =================== AIPass ====================
# Name: write_grant.py
# Version: 1.0.1
# Description: Whether a dispatch's write grant covers one cross-project write, read through @ai_mail's door
# Branch: hooks
# Layer: apps/modules
# Created: 2026-11-03
# Modified: 2026-11-04
# =============================================

"""Whether this session's dispatch grant covers one crossing write: @ai_mail's door decides, any doubt refuses."""

import importlib
import os
from dataclasses import dataclass
from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.hooks.apps.modules.write_ownership import Project
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

DISPATCH_ENV = "AIPASS_DISPATCH_ID"
_RAIL = "aipass.ai_mail.apps.modules.door_verified_caller"
_DOOR = "aipass.ai_mail.apps.modules.door_dispatch_grant"
UNREADABLE = "edit_gate could not read the dispatch register ({error}), so this crossing is refused."


@dataclass(frozen=True)
class Grant:
    """One crossing's ruling: allowed, or the lines a refusal adds ("" keeps the plain cross-project text)."""

    allowed: bool
    why: str = ""


def granted(cwd: str, caller_root: Path, landing: Project, target: Path) -> Grant:
    """Whether this session's dispatch grants *target* in foreign *landing*; no AIPASS_DISPATCH_ID is a plain no."""
    dispatch_id = os.environ.get(DISPATCH_ENV, "")
    if not dispatch_id:
        return Grant(False)
    try:
        return _ask(cwd, caller_root, landing, target, dispatch_id)
    # Every caller is a gate: a raising rail or door fails closed, and the warning tells it from a no.
    except Exception as exc:
        logger.warning("[HOOKS] write_grant: grant check for dispatch %s raised (refusing): %s", dispatch_id, exc)
        return Grant(False, UNREADABLE.format(error=exc))


def _ask(cwd: str, caller_root: Path, landing: Project, target: Path, dispatch_id: str) -> Grant:
    """The door's answer for one resolved target, with the refusal text it earns."""
    seat = _verified_caller(cwd)
    if not seat:
        return Grant(False, f"Dispatch {dispatch_id}'s grant was not read: the verified rail cannot name this seat.")
    # Judged after resolve: a symlink or a `..` must not carry a write out of a granted directory.
    resolved = target.resolve()
    if ".git" in resolved.parts:
        return Grant(False, f"Nothing under .git is ever granted ({resolved}); git stays with @devpulse.")
    door = importlib.import_module(_DOOR)
    # The caller's own register, never one planted under the landing root.
    decision = door.granted(seat, dispatch_id, str(resolved), repo_root=caller_root)
    reason = str(decision.get("reason") or "the door gave no reason")
    if decision.get("allowed") is True:
        logger.info(
            "[HOOKS] edit_gate: cross-project write ALLOWED by a dispatch grant: seat %s, project %s, dispatch %s (%s)",
            seat,
            landing.label,
            dispatch_id,
            resolved,
        )
        return Grant(True)
    ended = f"Dispatch {dispatch_id} grants nothing here: {reason}."
    # The door's words for an open grant that misses this path; any other reason means the grant cannot be used.
    if " is outside " not in reason:
        return Grant(False, ended)
    row = next((r for r in door.open_grants(repo_root=caller_root) if r.get("dispatch_id") == dispatch_id), {})
    grant = row.get(door.GRANT_KEY) or {}
    return Grant(
        False,
        f"{ended}\nIt grants, under {grant.get('root', '?')}: files {', '.join(grant.get('files', [])) or 'none'}; "
        f"directories (new files allowed under these) {', '.join(grant.get('dirs', [])) or 'none'}.\n"
        # An email, not a reply: replying closes the dispatch, and the grant with it.
        f"To widen it: drone @ai_mail email {row.get('sender') or '@devpulse'} "
        f"'Widen grant {dispatch_id[:8]}' 'need {resolved}'",
    )


def _verified_caller(cwd: str) -> str:
    """The seat @ai_mail's rail proves for *cwd*, the stamp never left behind; "" when unproven."""
    rail = importlib.import_module(_RAIL)
    stamped = not os.environ.get("AIPASS_CALLER_CWD") and bool(cwd)
    if stamped:
        os.environ["AIPASS_CALLER_CWD"] = cwd
    try:
        return str(rail.resolve_verified_caller() or "")
    finally:
        if stamped:
            os.environ.pop("AIPASS_CALLER_CWD", None)


def print_introspection() -> None:
    """Print module structure for drone routing: the contract, never a live verdict."""
    CONSOLE.print("[bold cyan]write_grant[/bold cyan] — does this dispatch's grant cover one cross-project write?")
    CONSOLE.print(f"[dim]Consumes {_DOOR}.granted and {_RAIL}.resolve_verified_caller.[/dim]")
    CONSOLE.print(
        "[dim]Consumed by handlers/security/edit_gate.py: tool lane, scripted lane, daemon confinement.[/dim]"
    )
    CONSOLE.print("[yellow]Fails closed:[/yellow] no dispatch id, an unproven seat, .git, or any raise all refuse.")
