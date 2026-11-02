# =================== AIPass ====================
# Name: stop_gate.py
# Description: Stop hook — a devpulse turn cannot end with work out and no baseline wire armed
# Version: 1.0.0
# Created: 2026-11-01
# Modified: 2026-11-01
# =============================================

"""Stop hook: refuse to end a devpulse turn while a dispatch this seat sent is out and no wire is armed.

The refusal reason is the arm command, so the wake carrying the completion is never forgotten.
"""

import json
import sys
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.watchdog import dispatches as _dispatches
from aipass.devpulse.apps.handlers.watchdog import registry as _registry
from aipass.devpulse.apps.handlers.watchdog import wire as _wire

SEAT = "@devpulse"
ARM = "drone @devpulse watchdog baseline --once"
_ALLOW = {"exit_code": 0, "stdout": ""}


def _is_devpulse(cwd: str) -> bool:
    """The hook runs for every seat; only devpulse's own turn is gated."""
    here = Path(cwd)
    return here.name == "devpulse" and (here / ".trinity" / "passport.json").is_file()


def out_for(seat: str) -> list[dict]:
    """Dispatches this seat sent that a wire could still deliver: open and not dead."""
    return [r for r in _dispatches.outstanding() if _dispatches.is_mine(r, seat) and not _wire._is_dead(r)]


def wire_live(session_id: str) -> bool:
    """A baseline wire registered by this session with a living pid."""
    for watch in _registry.list_active():
        if watch.get("type") == _wire._WIRE_KIND and (watch.get("metadata") or {}).get("session") == session_id:
            return True
    return False


def reason_for(rows: list[dict]) -> str:
    """The refusal: who is out, and the exact arm command."""
    named = ", ".join(f"{r.get('target', '?')} ({str(r.get('subject') or '')[:40]})" for r in rows[:3])
    return (
        f"Work is out with no watchdog wire for this session: {named}. "
        f"Arm it, then end the turn: Bash with run_in_background=true, bare: {ARM}"
    )


def handle(hook_data: dict) -> dict:
    """Block the Stop with the arm command while dispatches are out and no wire is live; else allow.

    stop_hook_active means this Stop already follows a block: allow, so a seat that cannot arm is not trapped.
    Any failure allows with the error on stderr: a broken gate must never hold the seat forever.
    """
    if hook_data.get("stop_hook_active") or not _is_devpulse(str(hook_data.get("cwd") or "")):
        return _ALLOW
    try:
        rows = out_for(SEAT)
        if not rows or wire_live(str(hook_data.get("session_id") or "")):
            return _ALLOW
    except Exception as exc:
        logger.warning("[watchdog.stop_gate] allowed, could not check the wire: %s", exc)
        sys.stderr.write(f"[watchdog.stop_gate] allowed, could not check the wire: {exc}\n")
        return _ALLOW
    json_handler.log_operation("stop_gate_refused", {"out": len(rows)})
    logger.warning("[watchdog.stop_gate] refused Stop: %s dispatch(es) out, no wire", len(rows))
    return {"exit_code": 2, "stdout": json.dumps({"decision": "block", "reason": reason_for(rows)})}
