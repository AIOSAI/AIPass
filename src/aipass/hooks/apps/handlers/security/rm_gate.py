# =================== AIPass ====================
# Name: rm_gate.py
# Version: 3.0.0
# Description: Refuses every raw rm, and every other delete off the admin seat; records each refused one (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-02
# Modified: 2026-10-17
# =============================================

"""Refuses deletes on the agent Bash tool, and writes every refused one down.

Failure mode: a crash refuses the Bash call it was checking; the engine refuses on import error and timeout.

Raw rm is refused for every seat; drone rm and every other delete (rmdir, unlink, find -delete,
an interpreter's readable delete) off the verified admin seat (admin_seat's grant, never a name).
What modules/shell_reader cannot read is refused off the admin seat too. Bash tool only:
service code running drone rm passes no hook. git rm answers to git_gate.
"""

import importlib
import json

from aipass.prax.apps.modules.logger import system_logger as logger


_DONT_DELETE = (
    "Don't delete. Move or rename instead — that is the safety feature: the owner sees the files and decides.\n"
    "  rename it    name(disabled).ext       e.g. mv old.py 'old(disabled).py'\n"
    "  archive it   move it into a .archive/ folder beside it\n"
    "               (create the folder if it isn't there: mkdir -p .archive && mv old.py .archive/)\n"
    "  or both.     Archived files can stay forever.\n"
    "\n"
    "It must truly go? Mail @devpulse with the path and why:\n"
    '  drone @ai_mail email @devpulse "Delete request" "<path>: <why>"\n'
    "\n"
    "This refused attempt is recorded."
)

RM_REFUSED = "Raw rm is refused for every seat (the owner's ruling, DPLAN-0356). Caller: {caller}.\n\n" + _DONT_DELETE

DRONE_RM_REFUSED = (
    "drone rm is the admin seat's alone (@devpulse, the owner's ruling, DPLAN-0356). Caller: {caller}, "
    "with no verified admin grant.\n\n" + _DONT_DELETE
)

RM_REFUSED_ADMIN = (
    "Raw rm is refused for every seat, the admin seat included (DPLAN-0356). Use:\n"
    "  drone rm <path>     # the logged, project-aware delete\n"
    "\n"
    "This refused attempt is recorded."
)

UNNAMED_CALLER = "could not be named (no readable passport above {cwd})"

GATE_CRASHED = (
    "rm_gate could not check this Bash call ({error}), so it is refused: a gate that cannot read a command "
    "does not let it through.\n"
    'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Gate broken: rm_gate" "<what you ran, and this text>"'
)

DELETE_REFUSED = (
    "{what} is a delete, and deletes are the admin seat's alone (@devpulse, the owner's ruling, "
    "DPLAN-0356). Caller: {caller}.\n\n" + _DONT_DELETE
)

UNREAD_REFUSED = (
    "This command runs something the gates cannot read: {what}. Caller: {caller}.\n"
    "A program the gates cannot see could delete or write anything, so off the admin seat it is refused "
    "(DPLAN-0356).\n"
    "\n"
    "Spell the program out: a literal command word, not a variable or a substitution; a script that exists "
    "and is readable before the command runs; a program handed to a shell or interpreter with -c or a "
    "heredoc rather than through a pipe.\n"
    'Need it as written? Mail @devpulse: drone @ai_mail email @devpulse "Command review" "<the command and why>"'
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}

# Delete verbs besides rm, read where a program runs, never as any word: `grep unlink`
# searches for the word, `unlink f` deletes f.
_DELETE_VERBS = frozenset({"rmdir", "unlink", "shred", "srm", "wipe", "trash", "trash-put", "rimraf"})

_DRONE = "drone"


def _block(reason: str) -> dict:
    return {"stdout": json.dumps({"decision": "block", "reason": reason}), "exit_code": 2, "sound": "rm gate"}


def _reader():
    """The branch's one shell-word reader (modules/shell_reader), imported at call time (crash isolation)."""
    return importlib.import_module("aipass.hooks.apps.modules.shell_reader")


def _seat(cwd: str) -> tuple[str | None, bool]:
    """(caller name, verified admin) from modules/admin_seat, fail-closed.

    An unimportable admin_seat names no one and grants no one: a missing module
    must never exempt every seat.
    """
    try:
        return importlib.import_module("aipass.hooks.apps.modules.admin_seat").seat_of(cwd)
    except Exception as exc:  # an unreachable seat module refuses rather than opens
        logger.warning("[HOOKS] rm_gate: admin lane dark — admin_seat unavailable, refusing as unnamed: %s", exc)
        return None, False


def _record(cmd: str, cwd: str, caller: str | None, lanes: dict[str, int]) -> None:
    """Write down every refused delete — one line per deleting program, its lane named.

    INFO by design: the engine already logs the block at WARNING; this adds cmd, cwd and caller.
    """
    for lane, count in lanes.items():
        for _ in range(count):
            logger.info(
                "[HOOKS] rm_gate: DELETE refused | lane=%s | branch=%s | cwd=%s | cmd=%s",
                lane,
                caller or "unnamed",
                cwd,
                cmd,
            )


def _classify(cmd: str, cwd: str) -> tuple[int, int, list[str], list[str]]:
    """(raw rm, drone rm, other deletes, what could not be read) across every program *cmd* runs."""
    reader = _reader()
    lanes: list[str] = []
    unread: list[str] = []
    for inv in reader.invocations(cmd, cwd):
        if inv.unread:
            unread.append(inv.unread)
        lanes.extend(_lanes_of(reader, inv))
    others = [lane for lane in lanes if lane not in ("rm", "drone rm")]
    return lanes.count("rm"), lanes.count("drone rm"), others, unread


def _lanes_of(reader, inv) -> list[str]:
    """What one program deletes: "rm", "drone rm", a delete verb, and its program text's delete shape."""
    shape = reader.program_delete(inv)
    found = [shape] if shape else []
    if inv.program == "rm":
        return ["rm", *found]
    if inv.program == _DRONE and len(inv.argv) > 1 and reader.verb_name(inv.argv[1]) == "rm":
        return ["drone rm", *found]
    if inv.program in _DELETE_VERBS:
        return [inv.program, *found]
    if inv.program == "find" and "-delete" in inv.argv[1:]:
        return ["find -delete", *found]
    return found


def _refusal(raw: int, drone: int, others: list[str], admin: bool, caller: str | None, cwd: str) -> str:
    """The refusal that teaches this caller its own way forward."""
    if raw and admin:
        return RM_REFUSED_ADMIN
    named = f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=cwd or "(no cwd)")
    if raw:
        return RM_REFUSED.format(caller=named)
    if drone:
        return DRONE_RM_REFUSED.format(caller=named)
    return DELETE_REFUSED.format(what=", ".join(dict.fromkeys(others)), caller=named)


def handle(hook_data: dict) -> dict:
    """Refuse every raw rm, and drone rm, every other delete and any unreadable program off the admin seat."""
    if not isinstance(hook_data, dict) or hook_data.get("tool_name", "") != "Bash":
        return _BLOCK_ALLOW
    try:
        cmd = hook_data.get("tool_input", {}).get("command", "")
        if not cmd:
            return _BLOCK_ALLOW
        cwd = hook_data.get("cwd", "")
        raw, drone, others, unread = _classify(cmd, cwd)
        if not raw and not drone and not others and not unread:
            return _BLOCK_ALLOW

        caller, admin = _seat(cwd)
        if not raw and admin:
            return _BLOCK_ALLOW
        if not raw and not drone and not others:
            named = f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=cwd or "(no cwd)")
            _record(cmd, cwd, caller, {"unread program": len(unread)})
            return _block(UNREAD_REFUSED.format(what="; ".join(dict.fromkeys(unread)), caller=named))

        _record(cmd, cwd, caller, {"raw rm": raw, "drone rm": drone, "delete verb": len(others)})
        return _block(_refusal(raw, drone, others, admin, caller, cwd))

    except Exception as exc:  # fail closed on the Bash call this gate guards
        logger.error("[HOOKS] rm_gate: crashed, refusing the Bash call: %s", exc)
        return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
