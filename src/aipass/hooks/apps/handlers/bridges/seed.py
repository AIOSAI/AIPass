# =================== AIPass ====================
# Name: seed.py
# Version: 1.1.0
# Description: Seed bridge — a hooks.json command row of a Seed head, handed to the engine, answered in Claude's shape
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-11-04
# Modified: 2026-11-15
# =============================================

"""Seed bridge.

Called from the Seed home's hooks.json ($SEED_HOME, else ~/.config/seed), whose rows `drone @hooks seed
install` writes. Seed already speaks Claude's names and stamps provider "seed", so nothing is renamed.
Seed's runner reads one JSON object on stdout, or nothing, and takes exit 2 as a block with stderr as
the reason; any other non-zero exit or a non-JSON stdout is a broken row. So a JSON answer passes as is,
plain text becomes context, and a block's reason goes to stderr. The hook code is the promoted copy
(mount.py); a PreToolUse whose hook code cannot load or raises is refused with exit 2. See docs/wiring.md.
"""

import contextlib
import importlib.util
import json
import os
import sys
import time

GUARDED_EVENTS = frozenset({"PreToolUse"})

PROVIDER = "seed"

SESSION_ENV = "CLAUDE_CODE_SESSION_ID"

PLAIN_IS_CONTEXT = frozenset({"SessionStart", "UserPromptSubmit"})

BROKEN = (
    "HOOKS BROKEN: the AIPass hook engine could not run ({error}).\n"
    "Every gate it runs is down, so nothing they guard runs until it is fixed.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'
)

#: Where a break is recorded: @trigger's branch watcher reads src/aipass/*/logs/*.log for ERROR lines.
BREAK_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "logs", "bridge.log")
LIVE_BREAK_LOG = BREAK_LOG


def _as_object(text: str) -> dict | None:
    """*text* as a JSON object, or None when it is plain text."""
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    return doc if isinstance(doc, dict) else None


def document(event_type: str, output: str) -> str:
    """The engine's exit-0 answer as Seed's runner parses it: a JSON object as is, plain text wrapped."""
    if not output.strip() or _as_object(output) is not None:
        return output
    if event_type in PLAIN_IS_CONTEXT:
        return json.dumps({"hookSpecificOutput": {"hookEventName": event_type, "additionalContext": output}})
    return json.dumps({"systemMessage": output})


def block_reason(output: str) -> str:
    """The reason of the engine's exit-2 answer: Seed reads it from stderr, never from stdout."""
    doc = _as_object(output) or {}
    own = doc.get("hookSpecificOutput")
    own = own if isinstance(own, dict) else {}
    return str(doc.get("reason") or own.get("permissionDecisionReason") or output.strip() or "Blocked by AIPass hook")


def _mount() -> str:
    """Serve aipass.hooks.apps from the promoted copy; on a bad copy, from the source tree, loudly."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("_aipass_hooks_mount", os.path.join(here, "mount.py"))
    if spec is None or spec.loader is None:
        raise ImportError("mount.py has no import spec")
    mount = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mount)
    return mount.mount_or_source(__file__, "seed")


def _printable(text: str) -> str:
    """*text* safe on a UTF-8 stream: a lone surrogate (a path that is not UTF-8) becomes its escape."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _record_break(event_type: str, line: str) -> None:
    """Append one ERROR line in prax's format, after the answer has left: an attempt, never a wait."""
    if "_pytest" in sys.modules and BREAK_LOG == LIVE_BREAK_LOG:
        return  # prax's own test seam: a suite run's break never lands in the live log medic reads
    try:
        entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | bridges.seed | ERROR | {line} on {event_type}\n"
        fd = os.open(BREAK_LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK, 0o666)
        try:
            os.write(fd, entry.encode("utf-8", "backslashreplace"))
        finally:
            os.close(fd)
    except BaseException as exc:  # the answer is already out: nothing the record raises may change it
        with contextlib.suppress(BaseException):
            sys.stderr.write(
                f"[HOOKS:seed] bridge: the break was not recorded in {BREAK_LOG}: {type(exc).__name__}: {exc}\n"
            )


def _broken(event_type: str, exc: BaseException) -> None:
    """Refuse a guarded event with exit 2; any other event answers nothing. Answer first, record after."""
    code = 2 if event_type in GUARDED_EVENTS else 0
    try:
        reason = _printable(BROKEN.format(error=f"{type(exc).__name__}: {exc}"))
        sys.stderr.write(reason + "\n")
        sys.stderr.flush()
        _record_break(event_type, reason.splitlines()[0])
    finally:
        if code:
            sys.exit(code)


def main() -> None:
    """Entry point — one Seed hook row: the event in argv, the payload on stdin, the engine's answer on stdout."""
    if len(sys.argv) < 2:
        sys.stderr.write("Usage: seed.py <EventType> or seed.py <EventType:hook_name>\n")
        sys.exit(1)
    arg = sys.argv[1]
    event_type = arg.split(":", 1)[0]

    try:
        stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()
        payload = _as_object(stdin_data)
        if payload is not None:
            if payload.get("session_id"):
                # Cadence and the ledgers key a seat on this variable; a Seed head inherits none, or its launcher's.
                os.environ[SESSION_ENV] = str(payload["session_id"])
            if "provider" not in payload:
                stdin_data = json.dumps({**payload, "provider": PROVIDER})
        _mount()
        from aipass.hooks.apps.modules.engine import run_event

        output, exit_code = run_event(arg, stdin_data)
    except BaseException as exc:  # fail closed on the guarded event, however it broke: see _broken
        _broken(event_type, exc)
        return

    try:
        if exit_code == 2:
            sys.stderr.write(_printable(block_reason(output)) + "\n")
            sys.stdout.write(_printable(output))
        else:
            sys.stdout.write(_printable(document(event_type, output)))
    finally:
        if exit_code:
            sys.exit(exit_code)


if __name__ == "__main__":
    main()
