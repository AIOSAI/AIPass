# =================== AIPass ====================
# Name: rm_gate.py
# Version: 3.0.0
# Description: Refuses every raw rm, and every other delete off the admin seat; records each refused one (PreToolUse)
# Branch: hooks
# Layer: apps/handlers/security
# Created: 2026-06-02
# Modified: 2026-10-01
# =============================================

"""Refuses deletes on the agent Bash tool, and writes every refused one down.

Failure mode: a crash refuses the Bash call it was checking; the engine refuses on import error and timeout.

The owner, 2026-09-30 (DPLAN-0356): "canary rm and git should of been blocked.
right. drone rm should only be known by u. only u should be able to use it."

  - A raw ``rm``, recursive or not, is refused for every seat, the admin seat
    included. The admin seat is taught ``drone rm``; every other seat is taught
    not to delete at all (the owner, 2026-09-30): rename to
    ``name(disabled).ext``, move into a ``.archive/`` folder beside it (made with
    ``mkdir -p .archive`` when it isn't there), or both; a file that truly must
    go is mailed to @devpulse with the path and why. Moving and renaming is the
    safety feature: the owner sees the files and decides.
  - ``drone rm`` is refused unless the session is the verified admin seat.
  - Every other delete is refused off the admin seat, with the same text (the
    owner, 2026-09-30, mail dab4e222: "rm is a big no no; only devpulse
    deletes"): ``rmdir``, ``unlink``, ``shred`` and their kin wherever a program
    runs, ``find -delete``, and an interpreter's delete when its program text can
    be read (inline, a heredoc, or since 3.0.0 the script FILE it is handed).
    ``find -exec rm`` and ``xargs rm`` are raw rm. Moving, renaming and ``mkdir``
    are never deletes.

Since 3.0.0 (DPLAN-0356 phase 3, the red team's R3 and R4) this gate reads no
text of its own. modules/shell_reader is the branch's one shell-word reader:
it hands back every program the command runs the way the shell will run it —
quotes removed, escapes and ``$'...'`` decoded, braces expanded, a glob in the
command word resolved, ``eval`` / ``bash -c`` / ``source`` / script files read.
What it cannot read (a program word that is an unfolded expansion, a script that
cannot be read, a shell fed from a pipe) is refused off the admin seat: a
program this gate cannot see is not one it lets through.

WHO is ``modules/admin_seat``'s verified 5-leg grant, never a directory name:
a seat standing in a directory called devpulse with no grant is refused. The
passport only NAMES the caller, in the refusal and in the record. A caller
with no passport is refused like any other non-admin seat, and told it could
not be named.

The gate acts on the agent's Bash tool only. Service code that runs
``drone rm`` as a subprocess (backup rotation, prax, test suites) never passes
through a hook and keeps working.

The deletion record stays (the owner, 2026-08-14: "if something deletes, it
should be a record of it"): every refused attempt is one line per deleting
program. An admin seat's allowed ``drone rm`` is @drone's to record, not this
gate's. ``git rm`` touches the index and answers to git_gate.
"""

import importlib
import json

from aipass.prax.apps.modules.logger import system_logger as logger


# The owner, 2026-09-30: "Agents are free to move or rename. That is the safety feature:
# the owner sees the files and decides. Archived files can stay forever."
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

# DPLAN-0356 phase 3 (R3, R4): what the reader could not see is not let through off the admin seat.
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

# `drone rm` is the admin seat's lane; `git rm` removes from the index and answers to git_gate.
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

    The command is logged as the agent wrote it. INFO by design (compass #273): the
    engine already records the block at WARNING, and this line adds the command,
    cwd and caller the engine never carried.
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
    """Refuse every raw rm, and drone rm, every other delete and any unreadable program off the admin seat.

    Args:
        hook_data: Parsed hook event dict from engine.

    Returns:
        Result dict with stdout (block JSON or empty) and exit_code.
    """
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

    except Exception as exc:  # fail closed on the Bash call this gate guards (DPLAN-0356 item 2)
        logger.error("[HOOKS] rm_gate: crashed, refusing the Bash call: %s", exc)
        return _block(GATE_CRASHED.format(error=f"{type(exc).__name__}: {exc}"))
