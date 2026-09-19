# =================== AIPass ====================
# Name: injection_ledger.py
# Version: 1.1.0
# Description: Per-turn record of what the engine injected into a session, keyed on cadence's turn token (warn-only)
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-16
# Modified: 2026-09-16
# =============================================

"""What a seat was told, and when — one JSONL record per injecting dispatch.

DPLAN-0347, hooks row 3. The argument this settles is "what was this seat told
at turn N": until now the only witnesses were engine.jsonl (about eleven
minutes of retention, and a stdout LENGTH with no idea whether that stdout was
context) and the agent's own memory of its prompt, which is the thing in doubt.

KEYED ON THE TURN TOKEN, NOT THE TURN NUMBER. UserPromptSubmit handlers run as
parallel processes, and the one that increments cadence's counter is not always
the first to finish — a sibling that never consults cadence (temporal) can read
the previous turn's number. The token is the transcript's size at the prompt,
identical in every sibling of one turn, so grouping by it is exact where the
number can lag by one. The number rides along for reading, never for grouping.

WARN-ONLY. Nothing reads the ledger to decide anything. It WARNS in two cases,
both of them a seat being told less than it looks like: an injection over the
harness persist line (the model got a 2,000-char preview, not the text), and a
record that could not be written (a gap in the ledger must not be silent).

The record's shape and file live in handlers/config/ledger_store.py; this
module decides when to write and routes the read verb.
"""

import argparse
import importlib
import os
import time

from aipass.cli.apps.modules import console
from aipass.hooks.apps.handlers.cli.help_flags import wants_help
from aipass.hooks.apps.handlers.config import ledger_store
from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax.apps.modules.logger import system_logger as logger

HELP_COMMANDS = [
    ("ledger", "What this session was told, one line per turn (--session <id>, --last N)"),
]


def _turn_token_and_number(payload: dict) -> tuple[int | None, int | None]:
    """cadence's token for this payload and its (possibly lagging) turn number."""
    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        return cadence.turn_token(payload), cadence.current_turn()
    except Exception as exc:  # noqa: BLE001 - a ledger line without a turn is still a record
        logger.info("[HOOKS] injection_ledger: turn unreadable, recorded without it: %s", exc)
        return None, None


def _automated(event_type: str, payload: dict) -> bool | None:
    """Whether the harness sent this prompt (DPLAN-0348); None off UserPromptSubmit or when unreadable.

    The 33 idle wakes of 09-16 were counted by reading transcripts. The row
    carries the answer cadence acted on, so the next audit counts rows.
    """
    if event_type != "UserPromptSubmit":
        return None
    try:
        cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
        return bool(cadence.is_automated(payload))
    except Exception as exc:  # noqa: BLE001 - a ledger line without the flag is still a record
        logger.info("[HOOKS] injection_ledger: automated flag unreadable, recorded without it: %s", exc)
        return None


def record(event_type: str, outputs: list[tuple[str, str, str]], merged: str, payload: dict) -> dict | None:
    """Append one record for a dispatch that injected something. Never gates.

    Args:
        event_type: The dispatched event.
        outputs: The engine's (hook_name, handler, stdout) triples, pre-merge.
        merged: The single document the engine printed.
        payload: The parsed hook payload (session_id, transcript_path).

    Returns:
        The record written, or None when nothing was injected or nothing could be written.
    """
    if event_type not in ledger_store.LEDGER_EVENTS:
        return None
    hooks = ledger_store.measure_hooks(event_type, outputs)
    if not hooks:
        return None
    session_id = str(payload.get("session_id", "") or "")
    if not ledger_store.is_session_id(session_id):
        logger.info(
            "[HOOKS] injection_ledger: no usable session_id in the payload, %s injection unrecorded", event_type
        )
        return None
    token, turn = _turn_token_and_number(payload)
    return ledger_store.append_record(
        session_id, event_type, hooks, merged, token, turn, automated=_automated(event_type, payload)
    )


def _default_session() -> tuple[str | None, str]:
    """The session a bare `ledger` reads, and how it was chosen.

    The caller's own session first. Every citizen runs a live session, so "the
    most recently written ledger" is usually a neighbour's: measured on
    2026-09-16, a bare read from this seat printed another branch's turns.
    Newest-written stays as the answer only when the caller has no ledger of
    its own (a shell outside Claude Code), and the header says so.
    """
    own = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if ledger_store.is_session_id(own) and ledger_store.ledger_path(own).exists():
        return own, "this session"
    newest = ledger_store.newest_session()
    return (newest, "most recently written, NOT this session") if newest else (None, "")


def print_introspection() -> None:
    """Print module structure for drone routing."""
    console.print("[bold cyan]injection_ledger[/bold cyan] — What each session was told, keyed on the turn token")
    console.print("  Connected Handlers: handlers/config/ - ledger_store.py")


def handle_command(command: str, args: list) -> bool:
    """Route `drone @hooks ledger`."""
    if command != "ledger":
        return False
    if not args:
        print_introspection()
    if wants_help(args):
        console.print("[bold cyan]ledger[/bold cyan] — what a session was told, one line per turn")
        console.print("  drone @hooks ledger                    this session (else the most recently written)")
        console.print("  drone @hooks ledger --session <id>     a named session")
        console.print("  drone @hooks ledger --last N           only the last N rows (default 20)")
        return True

    parser = argparse.ArgumentParser(prog="drone @hooks ledger", add_help=False)
    parser.add_argument("--session", default="")
    parser.add_argument("--last", type=int, default=20)
    opts, _unknown = parser.parse_known_args(args)
    session_id, chosen = (opts.session, "named") if opts.session else _default_session()
    if not session_id:
        console.print("No injection ledger found in the temp dir (nothing has been injected since it was cleared).")
        return True

    rows = ledger_store.read_turns(session_id)
    json_handler.log_operation("ledger_read", {"session": session_id, "rows": len(rows)})
    console.print(f"[bold]ledger[/bold] session {session_id} ({chosen}) — {len(rows)} injection moment(s)")
    for row in rows[-max(opts.last, 1) :]:
        stamp = time.strftime("%H:%M:%S", time.localtime(row.get("ts", 0)))
        turn = row.get("turn")
        parts = " ".join(f"{name}={meta.get('chars', 0)}" for name, meta in row["hooks"].items())
        marker = " automated" if row.get("automated") else ""
        console.print(
            f"{stamp} {row.get('event')}{marker} turn={turn if turn is not None else '?'} "
            f"token={row.get('token')} total={row['total']} | {parts}"
        )
    return True
