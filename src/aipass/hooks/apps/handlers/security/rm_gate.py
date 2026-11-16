# =================== AIPass ====================
# Name: rm_gate.py
# Version: 3.4.0
# Description: Refuses raw rm, other deletes off the admin seat, and drone rm outside the caller's branch (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-02
# Modified: 2026-11-15
# =============================================

"""Refuses deletes on the agent Bash tool, and writes every refused one down.

Failure mode: a crash refuses the Bash call it was checking; the engine refuses on import error and timeout.

Raw rm is refused for every seat; every other delete (rmdir, unlink, find -delete, an interpreter's
readable delete) off the verified admin seat (admin_seat's grant, never a name). drone rm moves an
in-tree target into .archive, so off that seat it runs when every target resolves strictly inside
the caller's own branch (the nearest passport above the session cwd) or the system temp dir.
What modules/shell_reader cannot read is refused off the admin seat too. Bash tool only:
service code running drone rm passes no hook. git rm answers to git_gate.
"""

import importlib
import json
import tempfile
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger


_DONT_DELETE = (
    "You do not delete. To have a file gone, use drone rm inside your own branch:\n"
    "  drone rm <path>     # moves it into the .archive/ beside it\n"
    "drone rm puts the file there for the user; you never put anything there yourself. "
    "That .archive/ is the user's folder: not your concern, and it can be emptied at any moment.\n"
    "\n"
    "Outside your own branch? Mail @devpulse with the path and why:\n"
    '  drone @ai_mail email @devpulse "Delete request" "<path>: <why>"\n'
    "\n"
    "This refused attempt is recorded."
)

RM_REFUSED = (
    "Raw rm is refused for every seat: nobody deletes with rm, @devpulse included. Caller: {caller}.\n\n" + _DONT_DELETE
)

DRONE_RM_REFUSED = (
    "drone rm moves a file into the .archive/ folder beside it. Files in the system temp dir and Python "
    "bytecode (__pycache__, *.pyc) are truly deleted instead.\n"
    "You may drone rm only inside your own branch or the system temp dir; @devpulse alone may do it elsewhere. "
    "Caller: {caller}.\n"
    "Refused: {why}\n"
    "\n"
    "Not yours to move? Mail @devpulse with the path and why:\n"
    '  drone @ai_mail email @devpulse "Delete request" "<path>: <why>"\n'
    "\n"
    "This refused attempt is recorded."
)

RM_REFUSED_ADMIN = (
    "Raw rm is refused for every seat, the admin seat included. Use:\n"
    "  drone rm <path>     # moves it into the .archive/ folder beside it\n"
    "Files in the system temp dir and Python bytecode (__pycache__, *.pyc) are truly deleted instead.\n"
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
    "{what} is a delete. Only @devpulse may run a delete like that; you may not. Caller: {caller}.\n\n" + _DONT_DELETE
)

UNREAD_REFUSED = (
    "This command runs something the gates cannot read: {what}. Caller: {caller}.\n"
    "A program the gates cannot see could delete or write anything, so it is refused for everyone but @devpulse.\n"
    "\n"
    "Spell the program out: a literal command word, not a variable or a substitution; a script that exists "
    "and is readable before the command runs; a program handed to a shell or interpreter with -c or a "
    "heredoc rather than through a pipe.\n"
    'Need it as written? Mail @devpulse: drone @ai_mail email @devpulse "Command review" "<the command and why>"'
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}

_DRONE = "drone"

_ADMIN_SEAT = "aipass.hooks.apps.modules.admin_seat"

# drone rm's help form alone runs nothing, so every seat may read it.
_HELP_FORMS = (("--help",), ("-h",))

# The shell may still expand these, so the path drone rm receives is not the word the gate reads.
_SHELL_EXPANDS = frozenset("$`*?[]{}~")


def system_temp() -> Path:
    """The system temp dir, resolved: the one place outside a branch where a citizen's drone rm runs."""
    return Path(tempfile.gettempdir()).resolve()


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
        return importlib.import_module(_ADMIN_SEAT).seat_of(cwd)
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


def _record_move(cmd: str, cwd: str, caller: str | None, count: int, target: str, reason: str) -> None:
    """Write down every refused drone rm: a move refused before drone ran, with the target and the reason."""
    for _ in range(count):
        logger.info(
            "[HOOKS] rm_gate: MOVE refused | lane=drone rm | branch=%s | cwd=%s | target=%s | reason=%s | cmd=%s",
            caller or "unnamed",
            cwd,
            target or "-",
            reason,
            cmd,
        )


def _classify(cmd: str, cwd: str) -> tuple[int, list, list[str], list[str]]:
    """(raw rm, the drone rm invocations, other deletes, what could not be read) across every program *cmd* runs."""
    reader = _reader()
    lanes: list[str] = []
    drones: list = []
    unread: list[str] = []
    for inv in reader.invocations(cmd, cwd):
        if inv.unread:
            unread.append(inv.unread)
        found = _lanes_of(reader, inv)
        if "drone rm" in found:
            drones.append(inv)
        lanes.extend(found)
    others = [lane for lane in lanes if lane not in ("rm", "drone rm")]
    return lanes.count("rm"), drones, others, unread


def _target(arg: str, runs_in: str) -> Path:
    """*arg* resolved as drone rm resolves it, a link judged where it lives; raises when it cannot be."""
    if arg.startswith("-"):
        raise ValueError(
            f"{arg}: an option, and only @devpulse may pass options to drone rm; a file: write it as ./{arg}"
        )
    if _SHELL_EXPANDS & set(arg):
        raise ValueError(f"{arg}: the shell still expands it, so the path it names is unknown here")
    path = Path(arg)
    if not path.is_absolute():
        if not runs_in:
            raise ValueError(f"{arg}: relative, and the directory it runs in is unknown here")
        path = Path(runs_in) / path
    if path.is_symlink():
        return path.parent.resolve(strict=True) / path.name
    return path.resolve(strict=True)


def _not_movable(drones: list, cwd: str) -> tuple[str, str] | None:
    """(why, resolved target or "") for a drone rm target not this seat's to move; None when each one is.

    Raises when a target cannot be resolved.
    """
    root = importlib.import_module(_ADMIN_SEAT).branch_root(cwd)
    places = [place for place in (root, system_temp()) if place is not None]
    for inv in drones:
        if inv.argv[2:] in _HELP_FORMS:
            continue
        if len(inv.argv) < 3:
            return "drone rm names no path.", ""
        for arg in inv.argv[2:]:
            target = _target(arg, inv.cwd)
            if target == root:
                return f"{target} is your own branch root; a branch is retired by @spawn, not by drone rm.", str(target)
            if not any(target != place and target.is_relative_to(place) for place in places):
                where = (
                    f"outside your own branch ({root})" if root else "in no branch of yours (no passport above the cwd)"
                )
                return f"{target} is {where} and the system temp dir.", str(target)
    return None


def _lanes_of(reader, inv) -> list[str]:
    """What one program deletes: "rm", "drone rm", a delete verb, and its program text's delete shape."""
    shape = reader.program_delete(inv)
    found = [shape] if shape else []
    if inv.program == "rm":
        return ["rm", *found]
    if inv.program == _DRONE and len(inv.argv) > 1 and reader.verb_name(inv.argv[1]) == "rm":
        return ["drone rm", *found]
    if inv.program in reader.DELETE_PROGRAMS:
        return [inv.program, *found]
    if inv.program == "find" and "-delete" in inv.argv[1:]:
        return ["find -delete", *found]
    return found


def _refusal(raw: int, others: list[str], admin: bool, caller: str | None, cwd: str, why: str) -> str:
    """The refusal that teaches this caller its own way forward."""
    if raw and admin:
        return RM_REFUSED_ADMIN
    named = f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=cwd or "(no cwd)")
    if raw:
        return RM_REFUSED.format(caller=named)
    if others:
        return DELETE_REFUSED.format(what=", ".join(dict.fromkeys(others)), caller=named)
    return DRONE_RM_REFUSED.format(caller=named, why=why)


def handle(hook_data: dict) -> dict:
    """Refuse raw rm; off the admin seat any other delete, unreadable program, or drone rm outside the own branch."""
    if not isinstance(hook_data, dict) or hook_data.get("tool_name", "") != "Bash":
        return _BLOCK_ALLOW
    try:
        cmd = hook_data.get("tool_input", {}).get("command", "")
        if not cmd:
            return _BLOCK_ALLOW
        cwd = hook_data.get("cwd", "")
        raw, drones, others, unread = _classify(cmd, cwd)
        if not raw and not drones and not others and not unread:
            return _BLOCK_ALLOW

        caller, admin = _seat(cwd)
        if not raw and admin:
            return _BLOCK_ALLOW
        why, moved = "", ""
        if drones and not raw and not others:
            try:
                verdict = (
                    (f"it also runs what the gates cannot read: {'; '.join(unread)}.", "")
                    if unread
                    else _not_movable(drones, cwd)
                )
            except (OSError, RuntimeError, ValueError) as exc:  # an unresolvable target is refused, never waved through
                logger.info("[HOOKS] rm_gate: drone rm target unresolvable, refusing: %s", exc)
                verdict = (f"a target cannot be resolved: {exc}.", "")
            if verdict is None:
                return _BLOCK_ALLOW
            why, moved = verdict
        if not raw and not drones and not others:
            named = f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=cwd or "(no cwd)")
            _record(cmd, cwd, caller, {"unread program": len(unread)})
            return _block(UNREAD_REFUSED.format(what="; ".join(dict.fromkeys(unread)), caller=named))

        _record(cmd, cwd, caller, {"raw rm": raw, "delete verb": len(others)})
        _record_move(cmd, cwd, caller, len(drones), moved, why or "refused with the delete beside it in this command")
        return _block(_refusal(raw, others, admin, caller, cwd, why))

    except Exception as exc:  # fail closed on the Bash call this gate guards
        logger.error("[HOOKS] rm_gate: crashed, refusing the Bash call: %s", exc)
        return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
