# =================== AIPass ====================
# Name: todo_report.py
# Description: Todo-pad reports for rollover run/check and the todo verbs (count, backlog, restore)
# Version: 1.1.0
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""
Todo-Pad Report Handler (DPLAN-0345)

Resolves the ONE branch a todo operation acts on, runs the roll, the count,
the backlog read or the restore, and returns what to say as
``{"level", "text"}`` - the rollover and todo modules print it. Never the
fleet: the branch is ``--branch @name`` or the branch the caller's working
directory sits in, and at the repo root nothing resolves, so nothing is
rolled, checked, counted or listed and one line says so.

The over-count check line carries the literal phrase ``ready for rollover``:
@hooks' PreCompact hook runs ``rollover run`` only when ``rollover check``
stdout contains it (hooks handlers/lifecycle/rollover.py).

``todo restore`` writes a ``.trinity/local.json``, so it acts on the CALLER's
own branch only: a ``--branch`` naming any other branch is refused, and so is
a caller who stands in no branch at all (a flag alone proves nothing about
whose pad it is).

Levels:
    ``line``    - a plain line, printed as written
    ``warning`` - no usable todos count, or (rollover check) a pad that could not be counted
    ``error``   - a refusal: unknown branch, name collision, a roll or restore
                  that did not land, an unusable backlog. Printed through
                  ``error()``, so the command exits non-zero.
"""

from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover import todo_roll

MODULE_NAME = "todo_report"

LINE = "line"
WARNING = "warning"
ERROR = "error"

# @hooks greps `rollover check` stdout for exactly this.
READY_PHRASE = "ready for rollover"


def _report(level: str, text: str) -> dict[str, str]:
    """One report: a level and the line to print."""
    return {"level": level, "text": text}


def numbers_label(numbers: list[Any]) -> str:
    """'#1, #2, #3' for a few rolled numbers, '#1 ... #62' for many."""
    labels = ["#?" if number is None else f"#{number}" for number in numbers]
    if len(labels) <= 5:
        return ", ".join(labels)
    return f"{labels[0]} ... {labels[-1]}"


def _stop(
    target: dict[str, Any], verb: str, what: str = "todo pad", hint: str = "pass --branch @name"
) -> dict[str, str] | None:
    """The report that ends the operation before it starts, or None to go on."""
    if target.get("error"):
        return _report(ERROR, f"Todos not {verb} - {target['error']}")
    if target.get("name") is None:
        reason = target.get("reason")
        return _report(LINE, f"Todos: no branch resolved ({reason}) - no {what} {verb}; {hint}")
    return None


def check_pad(branch: str | None = None) -> dict[str, str]:
    """
    Count ONE branch's todo pad against its configured count. Writes nothing.

    Args:
        branch: ``@name``, or None for the branch the caller's cwd sits in

    Returns:
        ``{"level", "text"}`` - over the count, the text says ``ready for rollover``
    """
    target = todo_roll.resolve_target(branch)
    stop = _stop(target, "checked")
    if stop is not None:
        return stop

    name = target["name"]
    status = detector.check_todos(target["local"], name)
    if not status.get("success"):
        logger.warning(f"[todo_report] @{name} todos not checked: {status.get('error')}")
        return _report(WARNING, f"@{name} todos not checked - {status.get('error')}")

    pad, count = status.get("pad"), status.get("count")
    json_handler.log_operation(
        "check_pad",
        {"branch": name, "pad": pad, "count": count, "over": bool(status.get("over"))},
        module_name=MODULE_NAME,
    )
    if count is None:
        return _report(WARNING, f"@{name} todos: pad {pad} - no usable todos count configured, nothing will roll")
    if status.get("over"):
        return _report(
            LINE,
            f"@{name} todos: pad {pad}/{count} - {status.get('excess')} {READY_PHRASE} "
            f"(oldest by number -> {target.get('backlog_display')})",
        )
    return _report(LINE, f"@{name} todos: pad {pad}/{count} - within count")


def roll_pad(branch: str | None = None) -> dict[str, str]:
    """
    Roll ONE branch's todo pad to its backlog file (todo_roll.roll_todos).

    Args:
        branch: ``@name``, or None for the branch the caller's cwd sits in

    Returns:
        ``{"level", "text"}`` - what rolled and where, or why nothing did
    """
    target = todo_roll.resolve_target(branch)
    stop = _stop(target, "rolled")
    if stop is not None:
        return stop

    name = target["name"]
    outcome = todo_roll.roll_todos(name, local_path=target["local"], backlog_path=target["backlog"])
    if not outcome.get("success"):
        return _report(ERROR, f"@{name} todos NOT rolled - {outcome.get('error')}")

    count = outcome.get("count")
    if not outcome.get("rolled"):
        return _report(LINE, f"@{name} todos: pad {outcome.get('pad_before')}/{count} - nothing to roll")
    label = numbers_label(list(outcome.get("numbers") or []))
    return _report(
        LINE,
        f"@{name} todos: rolled {outcome['rolled']} oldest ({label}) -> {outcome.get('backlog_display')}, "
        f"read back and verified; pad now {outcome.get('pad_after')}/{count}",
    )


# =============================================================================
# THE TODO VERBS (FPLAN-0590 row 5)
# =============================================================================


def pad_summary(branch: str | None = None) -> dict[str, str]:
    """
    ONE line for bare ``todo``: the pad against its configured count, and the backlog. Writes nothing.

    Args:
        branch: ``@name``, or None for the branch the caller's cwd sits in

    Returns:
        ``{"level", "text"}`` - e.g. ``memory: pad 6 of 10 · backlog 0 (no backlog yet: <path>)``
    """
    target = todo_roll.resolve_target(branch)
    stop = _stop(target, "counted")
    if stop is not None:
        return stop

    name = target["name"]
    status = detector.check_todos(target["local"], name)
    if not status.get("success"):
        logger.warning(f"[todo_report] @{name} pad not counted: {status.get('error')}")
        return _report(ERROR, f"{name}: pad not counted - {status.get('error')}")

    count = status.get("count")
    pad = f"pad {status.get('pad')} of {count}"
    if count is None:
        pad = f"pad {status.get('pad')} (no usable todos count configured - nothing rolls)"

    state = todo_roll.read_backlog(target["backlog"])
    if state["error"]:
        return _report(ERROR, f"{name}: {pad} · backlog unreadable - {state['error']}")
    where = target.get("backlog_display")
    backlog = f"backlog {len(state['entries'])} ({where})"
    if not state["exists"]:
        backlog = f"backlog 0 (no backlog yet: {where})"

    json_handler.log_operation(
        "pad_summary",
        {"branch": name, "pad": status.get("pad"), "count": count, "backlog": len(state["entries"])},
        module_name=MODULE_NAME,
    )
    return _report(LINE if count is not None else WARNING, f"{name}: {pad} · {backlog}")


def _shown(value: Any) -> str:
    """A record field as text, '?' when it is absent."""
    return "?" if value is None else str(value)


def record_line(index: int, record: Any) -> str:
    """
    One backlog record as one line: original number, date, priority when set, rolled, reason, task.

    ``status`` is never printed. Records rolled off before DPLAN-0345 can carry
    tens of thousands of characters there; the task is what the note says.

    Args:
        index: The record's position in ``entries`` (0-based)
        record: One ``entries`` record, as read

    Returns:
        The line, indented two spaces
    """
    entry = record.get("entry") if isinstance(record, dict) else None
    if not isinstance(entry, dict):
        found = type(entry if isinstance(record, dict) else record).__name__
        return f"  record {index + 1}: not a todo record ({found}) - left as written"

    number = entry.get("number")
    parts = [f"#{number}" if isinstance(number, int) and not isinstance(number, bool) else "#?"]
    parts.append(_shown(entry.get("date")))
    if entry.get("priority") not in (None, ""):
        parts.append(f"priority {entry['priority']}")
    parts.append(f"rolled {_shown(record.get('rolled'))}")
    parts.append(_shown(record.get("reason")))
    task = entry.get("task")
    parts.append(task if isinstance(task, str) else "(no task)")
    return "  " + " · ".join(parts)


def backlog_listing(branch: str | None = None) -> list[dict[str, str]]:
    """
    List ONE branch's backlog, one report per line. Writes nothing.

    A missing file is a state, not a failure: ``.backup/`` is gitignored, so a
    fresh clone has no backlog. An unusable file is an error.

    Args:
        branch: ``@name``, or None for the branch the caller's cwd sits in

    Returns:
        ``[{"level", "text"}, ...]`` - a header line, then one line per record
    """
    target = todo_roll.resolve_target(branch)
    stop = _stop(target, "listed", what="backlog", hint="pass @name")
    if stop is not None:
        return [stop]

    name, where = target["name"], target.get("backlog_display")
    state = todo_roll.read_backlog(target["backlog"])
    if state["error"]:
        return [_report(ERROR, f"{name}: backlog not listed - {state['error']}")]
    if not state["exists"]:
        return [
            _report(
                LINE,
                f"{name}: no backlog - {where} does not exist. Nothing has rolled off this pad on this machine "
                f"({todo_roll.BACKUP_DIR}/ is gitignored, so a fresh clone starts without one)",
            )
        ]

    entries = state["entries"]
    json_handler.log_operation("backlog_listing", {"branch": name, "records": len(entries)}, module_name=MODULE_NAME)
    header = _report(LINE, f"{name} backlog: {len(entries)} record(s), oldest roll first ({where})")
    return [header] + [_report(LINE, record_line(index, record)) for index, record in enumerate(entries)]


def parse_todo_number(token: str) -> int | None:
    """A todo number as typed (``7`` or ``#7``), or None when it is not a whole number."""
    text = token[1:] if token.startswith("#") else token
    return int(text) if text.isascii() and text.isdigit() else None


def _own_branch(branch: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """The caller's own branch target, or ``(None, refusal)`` - restore writes a pad, so only its own."""
    caller = todo_roll.resolve_target(None)
    if caller.get("error"):
        return None, caller["error"]
    if caller.get("name") is None:
        return None, (
            f"no branch resolved from where you stand ({caller.get('reason')}) - restore writes a "
            ".trinity/local.json, so run it from inside your own branch"
        )
    if branch is None:
        return caller, None

    named = todo_roll.resolve_target(branch)
    if named.get("error"):
        return None, named["error"]
    if str(named["name"]).lower() != str(caller["name"]).lower():
        return None, (
            f"--branch names @{named['name']}, but you are in @{caller['name']} - restore writes that branch's "
            f".trinity/local.json, and only its own agent does that; run it from inside @{named['name']}"
        )
    return caller, None


def restore_pad(number_token: str, branch: str | None = None) -> dict[str, str]:
    """
    Move ONE backlog todo back onto the CALLER's own pad (todo_roll.restore_todo).

    Every refusal is an ``error`` report: a restore that did not happen must
    not exit 0. "Full" is the configured count, read inside ``restore_todo``.

    Args:
        number_token: The todo's ORIGINAL number as typed (``7`` or ``#7``)
        branch: ``@name`` from ``--branch``; refused unless it is the caller's own branch

    Returns:
        ``{"level", "text"}`` - old number -> new number and the task, or why nothing moved
    """
    number = parse_todo_number(number_token)
    if number is None:
        return _report(ERROR, f"Todo not restored - '{number_token}' is not a todo number (a whole number, e.g. 7)")
    target, refusal = _own_branch(branch)
    if target is None:
        logger.info(f"[todo_report] restore #{number} refused: {refusal}")
        return _report(ERROR, f"Todo #{number} not restored - {refusal}")

    name = target["name"]
    outcome = todo_roll.restore_todo(name, number, local_path=target["local"], backlog_path=target["backlog"])
    if not outcome.get("success"):
        logger.info(f"[todo_report] @{name} restore #{number} refused: {outcome.get('error')}")
        return _report(ERROR, f"@{name} todo #{number} NOT restored - {outcome.get('error')}")
    return _report(
        LINE,
        f"@{name} todo restored: #{number} -> #{outcome.get('number')} · {outcome.get('task')} · "
        f"pad now {outcome.get('pad')}/{outcome.get('count')}",
    )
