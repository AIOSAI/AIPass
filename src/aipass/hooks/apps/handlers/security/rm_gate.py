# =================== AIPass ====================
# Name: rm_gate.py
# Version: 3.7.1
# Description: Refuses raw rm, other deletes off the admin seat, and drone rm outside the caller's branch (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-02
# Modified: 2026-11-22
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

from aipass.hooks.apps.handlers.json import json_handler
from aipass.prax import logger


_DONT_DELETE = (
    "You do not delete. To have a file gone, use drone rm inside your own branch:\n"
    "  drone rm <path>     # moves it into the .archive/ beside it\n"
    "drone rm puts the file there for the user; you never put anything there yourself. "
    "That .archive/ is the user's folder: not your concern, and it can be emptied at any moment.\n"
    "\n"
    "Outside your own branch? Mail @devpulse with the path and why:\n"
    '  drone @ai_mail email @devpulse "Delete request" "<path>: <why>"\n'
    "\n"
    "{recorded}"
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
    "{recorded}"
)

RM_REFUSED_ADMIN = (
    "Raw rm is refused for every seat, the admin seat included. Use:\n"
    "  drone rm <path>     # moves it into the .archive/ folder beside it\n"
    "Files in the system temp dir and Python bytecode (__pycache__, *.pyc) are truly deleted instead.\n"
    "\n"
    "{recorded}"
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
    'Need it as written? Mail @devpulse: drone @ai_mail email @devpulse "Command review" "<the command and why>"\n'
    "\n"
    "{recorded}"
)

_BLOCK_ALLOW = {"stdout": "", "exit_code": 0}

_DRONE = "drone"

_ADMIN_SEAT = "aipass.hooks.apps.modules.admin_seat"
_OWNERSHIP = "aipass.hooks.apps.modules.write_ownership"
_LEDGER_DOOR = "aipass.drone"

RECORDED = "This refused attempt is recorded in .ai_central/deletions.jsonl."
NOT_RECORDED = "Recording this refused attempt in the ledger failed; the failure is logged."

# drone rm's help form alone runs nothing, so every seat may read it.
_HELP_FORMS = (("--help",), ("-h",))

# The shell may still expand these, so the path drone rm receives is not the word the gate reads.
_SHELL_EXPANDS = frozenset("$`*?[]{}~")

_TARGET_GRAMMAR = frozenset({"rm", "rmdir", "unlink"})


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
        logger.warning("[hooks] rm_gate: admin lane dark — admin_seat unavailable, refusing as unnamed: %s", exc)
        return None, False


def _record(cmd: str, cwd: str, caller: str | None, lanes: dict[str, int]) -> None:
    """Write down every refused delete — one line per deleting program, its lane named.

    INFO by design: the engine already logs the block at WARNING; this adds cmd, cwd and caller.
    """
    for lane, count in lanes.items():
        for _ in range(count):
            logger.info(
                "[hooks] rm_gate: DELETE refused | lane=%s | branch=%s | cwd=%s | cmd=%s",
                lane,
                caller or "unnamed",
                cwd,
                cmd,
            )


def _record_move(cmd: str, cwd: str, caller: str | None, count: int, target: str, reason: str) -> None:
    """Write down every refused drone rm: a move refused before drone ran, with the target and the reason."""
    for _ in range(count):
        logger.info(
            "[hooks] rm_gate: MOVE refused | lane=drone rm | branch=%s | cwd=%s | target=%s | reason=%s | cmd=%s",
            caller or "unnamed",
            cwd,
            target or "-",
            reason,
            cmd,
        )


def _ledger(cmd: str, cwd: str, caller: str | None, targets: list[str], reason: str) -> str:
    """A row per resolved target (one with no path when there is none) through @drone's door; the closing sentence.

    A row that cannot be written never lets the command through: the refusal stands and says so.
    """
    try:
        project = importlib.import_module(_OWNERSHIP).project_of(Path(cwd)) if cwd else None
        door = importlib.import_module(_LEDGER_DOOR)
        for target in targets or [None]:
            door.record_gate_refusal(
                caller=caller or "unknown",
                cwd=cwd,
                requested=cmd,
                resolved=target,
                reason=reason,
                project_root=project.root if project else None,
            )
    except Exception as exc:  # the refusal is already decided; a lost row is logged, never an allow
        logger.error("[hooks] rm_gate: ledger write failed, the refusal stands: %s", exc)
        return NOT_RECORDED
    return RECORDED


def _targets(cmd: str, cwd: str) -> list[str]:
    """Each operand of rm, rmdir, unlink and drone rm, resolved as the path it names (a link, not what it points to).

    Only these: no option of theirs takes a value. A word the shell still expands names no path here.
    """
    reader = _reader()
    found = []
    for inv in reader.invocations(cmd, cwd):
        if inv.program in _TARGET_GRAMMAR:
            words = inv.argv[1:]
        elif inv.program == _DRONE and len(inv.argv) > 1 and reader.verb_name(inv.argv[1]) == "rm":
            words = inv.argv[2:]
        else:
            continue
        operands = False
        for word in words:
            if not operands and (word == "--" or word.startswith("-")):
                operands = word == "--"
                continue
            if _SHELL_EXPANDS & set(word) or not (inv.cwd or word.startswith("/")):
                continue
            path = Path(inv.cwd) / word
            found.append(str(path.resolve() if path.name in ("", "..") else path.parent.resolve() / path.name))
    return list(dict.fromkeys(found))


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


def _refusal(raw: int, others: list[str], admin: bool, caller: str | None, cwd: str, why: str, recorded: str) -> str:
    """The refusal that teaches this caller its own way forward."""
    if raw and admin:
        return RM_REFUSED_ADMIN.format(recorded=recorded)
    named = f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=cwd or "(no cwd)")
    if raw:
        return RM_REFUSED.format(caller=named, recorded=recorded)
    if others:
        return DELETE_REFUSED.format(what=", ".join(dict.fromkeys(others)), caller=named, recorded=recorded)
    return DRONE_RM_REFUSED.format(caller=named, why=why, recorded=recorded)


def _ledger_reason(raw: int, others: list[str], why: str) -> str:
    """The one-sentence reason the ledger row carries."""
    if raw:
        return "raw rm is refused for every seat."
    if others:
        return f"{', '.join(dict.fromkeys(others))} is a delete only @devpulse may run."
    return why


def handle(hook_data: dict) -> dict:
    """Refuse raw rm and, off the admin seat, other deletes; each call leaves one json trail entry."""
    result = _decide(hook_data)
    payload = hook_data if isinstance(hook_data, dict) else {}
    tool = payload.get("tool_name") or payload.get("hook_event_name", "")
    verdict = "refuse" if result.get("exit_code") == 2 else "allow"
    json_handler.log_operation("check", {"tool": tool, "verdict": verdict, "seat": payload.get("cwd", "")})
    return result


def _decide(hook_data: dict) -> dict:
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
                logger.info("[hooks] rm_gate: drone rm target unresolvable, refusing: %s", exc)
                verdict = (f"a target cannot be resolved: {exc}.", "")
            if verdict is None:
                return _BLOCK_ALLOW
            why, moved = verdict
        if not raw and not drones and not others:
            named = f"@{caller}" if caller else UNNAMED_CALLER.format(cwd=cwd or "(no cwd)")
            what = "; ".join(dict.fromkeys(unread))
            _record(cmd, cwd, caller, {"unread program": len(unread)})
            recorded = _ledger(cmd, cwd, caller, _targets(cmd, cwd), f"it runs what the gates cannot read: {what}.")
            return _block(UNREAD_REFUSED.format(what=what, caller=named, recorded=recorded))

        _record(cmd, cwd, caller, {"raw rm": raw, "delete verb": len(others)})
        _record_move(cmd, cwd, caller, len(drones), moved, why or "refused with the delete beside it in this command")
        targets = ([moved] if moved else []) if why else _targets(cmd, cwd)
        recorded = _ledger(cmd, cwd, caller, targets, _ledger_reason(raw, others, why))
        return _block(_refusal(raw, others, admin, caller, cwd, why, recorded))

    except Exception as exc:  # fail closed on the Bash call this gate guards
        logger.error("[hooks] rm_gate: crashed, refusing the Bash call: %s", exc)
        return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
