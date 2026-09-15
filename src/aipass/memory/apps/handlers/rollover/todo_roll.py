# =================== AIPass ====================
# Name: todo_roll.py
# Description: Todo pad roll-off to .backup/todo/<branch>/backlog.json, file only, verified before the pad is pruned
# Version: 1.1.1
# Created: 2026-09-15
# Modified: 2026-09-15
# =============================================

"""Todo Roll Handler (DPLAN-0345 row 1, FPLAN-0590)

A branch's todos are a sticky-note pad: at most N live, where N is
``rollover.defaults.local.todos.count`` resolved per branch by
``config_loader.get_todos_count`` (never a literal). When the pad holds more,
the OLDEST by ``number`` roll off to a plain JSON file::

    <repo_root>/.backup/todo/<branch_dir>/backlog.json

FILE ONLY. No embedding, no ChromaDB, no subprocess, no extractor, no
orchestrator. A vectorized rolled todo is the CPLAN-0002 duplicate species:
restore then re-roll lands a second copy with nothing linking the two.

THE ORDER IS THE CONTRACT. The classic rollover prunes first and restores on
failure, which is wrong for open work. Here: append to the backlog, replace it
atomically, read it back and compare every record json-equal, and only then
write the pruned pad. Any mismatch refuses and leaves the pad untouched. A
todo may end up in both places; it must never end up in neither.

OWN BRANCH ONLY. Nothing on the detached fleet walk
(``auto_process._run_rollover_check`` -> ``detector.check_all_branches`` ->
``orchestrator.execute_rollover``) calls this module. A roll names ONE branch:
``--branch @name``, or the branch the caller's working directory sits in.

KEYED BY DIRECTORY. Registry names are mixed case (BACKUP); the trinity push
resolves ``name_from="path"``, so the backlog directory is the branch
directory name. Residents under ``projects/<name>/`` share the repo-root
``.backup/todo/``, so two in-scope branches sharing a directory name are
REFUSED by name: their backlogs would merge.

``.backup/`` is gitignored. A fresh clone has no backlog, and that is a state
("no backlog"), never an error.

Backlog document (nested, so the todo itself stays closed and json-comparable)::

    {"document_metadata": {"managed_by": "memory", "branch": "<dir>", "high_water": <int>},
     "entries": [{"rolled": "<iso>", "reason": "overflow|non-canonical|migration",
                  "entry": {<the todo, json-equal to the pad's copy>}}]}

NUMBERS ARE NEVER RE-ISSUED ON PURPOSE. ``high_water`` is the highest todo
number memory has seen for the branch, raised (never lowered) on every
backlog write; a backlog written before it existed has no floor, never an
error. The next number is one past the highest of the pad, the backlog's
original numbers, ``high_water`` and the ``next #N`` the branch's own tab last
rendered (N - 1). Residual: a todo added by hand and deleted by hand with no
memory write or tab render in between leaves no trace, so its number can be
issued again once.
"""

import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from aipass.prax import logger
from aipass.memory.apps.handlers import repo_root
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json.memory_files import read_memory_file, write_memory_file
from aipass.memory.apps.handlers.monitor import registry_scope

MODULE_NAME = "todo_roll"

BACKUP_DIR = ".backup"
TODO_DIR = "todo"
BACKLOG_FILE = "backlog.json"
MANAGED_BY = "memory"
TRINITY_DIR = ".trinity"
LOCAL_FILE = "local.json"

REASON_OVERFLOW = "overflow"
REASON_NON_CANONICAL = "non-canonical"
REASON_MIGRATION = "migration"
REASONS = (REASON_OVERFLOW, REASON_NON_CANONICAL, REASON_MIGRATION)

# document_metadata key: the highest todo number memory has seen for the branch.
HIGH_WATER_KEY = "high_water"

# memory's own todos tab (tab_renderer._todos_tab) ends its first ⟦ ⟧ with
# "· next #N ⟧". Only that shape is read; "#?", another tab or free text is no floor.
_TAB_NEXT_RE = re.compile(r"⟦ [^⟧]* · next #([1-9][0-9]*) ⟧")

# Drone stamps both on every branch it invokes. CALLER_CWD is EVIDENCE of where
# the caller stood. BRANCH_NAME without CALLER_CWD means this process's working
# directory was picked by whoever launched it (drone runs a branch from the
# branch's own directory), so the process cwd says nothing about the caller.
# AIPASS_CALLER_BRANCH is deliberately never read: at a repo root drone stamps
# the PROJECT name there, which collides with the @aipass citizen.
CALLER_CWD_VAR = "AIPASS_CALLER_CWD"
BRANCH_NAME_VAR = "AIPASS_BRANCH_NAME"


# =============================================================================
# SMALL PURE HELPERS
# =============================================================================


def _find_repo_root() -> Path:
    """Repo root for this lane, resolved by ``handlers/repo_root.py`` (never the process cwd)."""
    return repo_root.find_repo_root(caller=MODULE_NAME)


def _canonical(value: Any) -> str:
    """JSON equality spelled as text: key order ignored, types strict (1, 1.0 and true differ)."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _as_number(value: Any) -> int | None:
    """*value* when it is a real integer, else None (a bool is not a number)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _number_of(todo: Any) -> int | None:
    """A todo's number when it is a real integer, else None (a bool is not a number)."""
    if not isinstance(todo, dict):
        return None
    return _as_number(todo.get("number"))


def _age(todo: Any, index: int) -> tuple[int, int, int]:
    """Sort key, oldest first: ascending number; a todo with no usable number counts as oldest."""
    number = _number_of(todo)
    if number is None:
        return (0, 0, index)
    return (1, number, index)


def high_water_of(document: Any) -> int | None:
    """The ``document_metadata.high_water`` a backlog document carries, or None.

    A backlog without the key (every one written before it existed) or with a
    value that is not a real integer has no floor - never an error.
    """
    metadata = document.get("document_metadata") if isinstance(document, dict) else None
    return _as_number(metadata.get(HIGH_WATER_KEY)) if isinstance(metadata, dict) else None


def floor_from_tab(todos_meta: Any) -> int | None:
    """N - 1 from the ``next #N`` in the todos tab memory last rendered, or None for ``#?`` or any other text."""
    match = _TAB_NEXT_RE.match(todos_meta) if isinstance(todos_meta, str) else None
    return int(match.group(1)) - 1 if match else None


def _highest(pad: list[Any], backlog_entries: list[Any], *floors: Any) -> int | None:
    """The highest real integer among pad numbers, backlog original numbers and *floors*, or None."""
    numbers = [n for n in (_number_of(todo) for todo in pad) if n is not None]
    for record in backlog_entries:
        if isinstance(record, dict):
            number = _number_of(record.get("entry"))
            if number is not None:
                numbers.append(number)
    numbers.extend(n for n in (_as_number(floor) for floor in floors) if n is not None)
    return max(numbers) if numbers else None


def next_number(
    pad: list[Any],
    backlog_entries: list[Any],
    *,
    high_water: int | None = None,
    tab_floor: int | None = None,
) -> int:
    """The next todo number: one past the highest number memory can see for the branch.

    Args:
        pad: The live todos list.
        backlog_entries: The backlog's ``entries`` records.
        high_water: The backlog's :func:`high_water_of`, or None.
        tab_floor: :func:`floor_from_tab` of the branch's current ``todos_meta``, or None.

    Returns:
        max(pad numbers, backlog original numbers, high_water, tab_floor) + 1,
        or 1 when none holds a real integer.
    """
    highest = _highest(pad, backlog_entries, high_water, tab_floor)
    return highest + 1 if highest is not None else 1


def _stamp_high_water(document: dict[str, Any], pad: list[Any], *issued: int) -> None:
    """Raise *document*'s ``high_water`` to the highest number on *pad*, in its entries, or *issued*; never lower it."""
    highest = _highest(pad, document["entries"], high_water_of(document), *issued)
    if highest is not None:
        document["document_metadata"][HIGH_WATER_KEY] = highest


def _valid_dir_name(name: str) -> bool:
    """A single directory component: no separators, not empty, not a dot entry."""
    return bool(name) and name not in (".", "..") and Path(name).name == name


def _display(path: Path) -> str:
    """The path relative to the repo root when it sits inside it, else in full - posix separators either way."""
    try:
        return Path(path).relative_to(_find_repo_root()).as_posix()
    except ValueError:
        logger.debug(f"[todo_roll] {path} sits outside the repo root - shown in full")
        return Path(path).as_posix()


# =============================================================================
# WHERE A PAD AND ITS BACKLOG LIVE
# =============================================================================


def backlog_path_for(branch_dir: str, backup_root: Path | None = None) -> Path:
    """The backlog file for one branch directory name.

    Args:
        branch_dir: The branch DIRECTORY name (not the registry name).
        backup_root: The ``.backup`` directory to use; defaults to ``<repo_root>/.backup``.

    Returns:
        ``<backup_root>/todo/<branch_dir>/backlog.json``.
    """
    root = Path(backup_root) if backup_root is not None else _find_repo_root() / BACKUP_DIR
    return root / TODO_DIR / branch_dir / BACKLOG_FILE


def in_scope_branches(root: Path | None = None) -> list[dict[str, Any]]:
    """Core citizens and passport-declared residents, named by directory.

    The external tier is excluded: this lane writes, and no memory writer
    reaches outside this repository.

    Args:
        root: Repo root; defaults to this checkout's.

    Returns:
        ``registry_scope.fleet_branches`` rows without the external tier.
    """
    base = Path(root) if root is not None else _find_repo_root()
    return [
        item
        for item in registry_scope.fleet_branches(base, name_from="path")
        if item.get("residency") != registry_scope.RESIDENCY_EXTERNAL
    ]


def _no_target(error: str | None = None, reason: str | None = None) -> dict[str, Any]:
    """A resolution that names no branch: *error* is a refusal, *reason* is an honest 'nothing here'."""
    return {
        "name": None,
        "path": None,
        "local": None,
        "backlog": None,
        "backlog_display": None,
        "error": error,
        "reason": reason,
    }


def _target(name: str, branch_path: Path, local_path: Path, backlog: Path) -> dict[str, Any]:
    """A resolved branch: its directory name, pad file and backlog file."""
    return {
        "name": name,
        "path": branch_path,
        "local": local_path,
        "backlog": backlog,
        "backlog_display": _display(backlog),
        "error": None,
        "reason": None,
    }


def _collision(name: str, scope: list[dict[str, Any]]) -> str | None:
    """Refusal text when more than one in-scope branch shares *name* as a directory name."""
    sharing = [item for item in scope if str(item.get("name", "")).lower() == name.lower()]
    if len(sharing) <= 1:
        return None
    holders = "; ".join(f"{item.get('residency', 'unknown')} at {item.get('path')}" for item in sharing)
    return (
        f"REFUSED: directory name '{name}' is shared by {len(sharing)} branches ({holders}) - "
        f"their todo backlogs would merge in {BACKUP_DIR}/{TODO_DIR}/{name}/{BACKLOG_FILE}"
    )


def _from_scope(item: dict[str, Any], scope: list[dict[str, Any]], backup_root: Path | None) -> dict[str, Any]:
    """Turn one scope row into a target, refusing a directory-name collision."""
    collision = _collision(str(item["name"]), scope)
    if collision:
        logger.error(f"[todo_roll] {collision}")
        return _no_target(error=collision)
    branch_path = Path(item["path"])
    local = branch_path / TRINITY_DIR / LOCAL_FILE
    return _target(str(item["name"]), branch_path, local, backlog_path_for(str(item["name"]), backup_root))


def _resolved(path: Path) -> Path:
    """*path* resolved when the filesystem allows, else as spelled."""
    try:
        return Path(path).resolve()
    except OSError as exc:
        logger.debug(f"[todo_roll] Cannot resolve {path} ({type(exc).__name__}) - comparing its spelling")
        return Path(path)


def _caller_cwd(environ: Mapping[str, str]) -> tuple[Path | None, str | None]:
    """Where the caller stood, or ``(None, reason)`` when there is no evidence.

    Drone stamps the caller's directory and runs @memory from memory's own
    directory, so the process cwd answers only when nothing was stamped - and
    not when a branch name is set, because a launcher that names its target
    and stands in its directory would make every caller look like that branch.
    """
    if not environ.get(CALLER_CWD_VAR) and environ.get(BRANCH_NAME_VAR):
        return None, f"{BRANCH_NAME_VAR} is set without {CALLER_CWD_VAR}, so no caller directory is known"
    try:
        return Path(environ.get("AIPASS_CALLER_CWD") or Path.cwd()), None
    except OSError as exc:
        logger.warning(f"[todo_roll] Working directory unreadable ({type(exc).__name__}) - no caller branch")
        return None, f"the working directory is unreadable ({type(exc).__name__})"


def _containing_branch(where: Path, scope: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The deepest in-scope branch whose directory is *where* or contains it."""
    spot = _resolved(where)
    best: dict[str, Any] | None = None
    best_depth = -1
    for item in scope:
        branch_path = _resolved(Path(item["path"]))
        inside = spot == branch_path or branch_path in spot.parents
        if inside and len(branch_path.parts) > best_depth:
            best, best_depth = item, len(branch_path.parts)
    return best


def resolve_target(
    branch: str | None = None,
    *,
    fleet: list[dict[str, Any]] | None = None,
    backup_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve the ONE branch a todo operation acts on.

    Args:
        branch: ``@name`` or ``name`` (directory name, case-insensitive). None
            resolves the caller's branch from ``AIPASS_CALLER_CWD`` (or the
            process cwd when no launcher stamped one).
        fleet: Scope rows to resolve against; defaults to :func:`in_scope_branches`.
        backup_root: ``.backup`` override for the backlog path.
        environ: Environment override; defaults to ``os.environ``.

    Returns:
        ``{"name", "path", "local", "backlog", "backlog_display", "error", "reason"}``.
        ``name`` is None when nothing resolved: ``error`` carries a refusal
        (unknown branch, directory-name collision), ``reason`` an honest
        "no branch here" (repo root, outside every branch).
    """
    scope = list(fleet) if fleet is not None else in_scope_branches()

    if branch is not None:
        wanted = branch.strip().lstrip("@")
        matches = [item for item in scope if str(item.get("name", "")).lower() == wanted.lower()]
        if not matches:
            known = ", ".join(sorted(str(item.get("name")) for item in scope))
            return _no_target(error=f"Unknown branch: @{wanted} - in scope: {known}")
        return _from_scope(matches[0], scope, backup_root)

    where, reason = _caller_cwd(os.environ if environ is None else environ)
    if where is None:
        return _no_target(reason=reason)
    item = _containing_branch(where, scope)
    if item is None:
        return _no_target(reason=f"{where} is not inside a registered branch directory")
    return _from_scope(item, scope, backup_root)


def _locate(
    branch: str,
    local_path: Path | None,
    backlog_path: Path | None,
    backup_root: Path | None,
    fleet: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Registry resolution by default; explicit files (scratch copies) when *local_path* is given."""
    if local_path is None:
        target = resolve_target(branch, fleet=fleet, backup_root=backup_root)
    else:
        name = branch.strip().lstrip("@")
        if not _valid_dir_name(name):
            return _no_target(error=f"'{branch}' is not a branch directory name")
        local = Path(local_path)
        target = _target(name, local.parent.parent, local, backlog_path_for(name, backup_root))
    if backlog_path is not None and target["name"] is not None:
        target["backlog"] = Path(backlog_path)
        target["backlog_display"] = _display(Path(backlog_path))
    return target


def _pad_count(name: str) -> tuple[int | None, str | None]:
    """The pad size for *name* from config, or ``(None, refusal)``."""
    count = config_loader.get_todos_count(name)
    if count is None:
        return None, f"no usable todos count for @{name} (rollover.defaults.local.todos.count) - nothing moved"
    return count, None


# =============================================================================
# FILE I/O THROUGH THE HOUSE WRITER
# =============================================================================


def _read_document(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Read one JSON object through ``memory_files.read_memory_file``."""
    result = read_memory_file(Path(path))
    if not result.get("success"):
        return None, str(result.get("error"))
    data = result.get("data")
    if not isinstance(data, dict):
        return None, f"{Path(path).name} is a JSON {type(data).__name__}, not an object"
    return data, None


def _write_document(path: Path, document: dict[str, Any]) -> str | None:
    """Atomic write (temp file + os.replace) through ``memory_files.write_memory_file``.

    Returns:
        The writer's refusal, or None when the file was replaced.
    """
    result = write_memory_file(Path(path), document)
    if result.get("success"):
        return None
    return str(result.get("error") or "the memory-file writer refused without a reason")


def _ensure_parent(path: Path) -> str | None:
    """Create *path*'s directory; returns the failure, or None."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.error(f"[todo_roll] Cannot create {Path(path).parent}: {exc}")
        return f"cannot create {Path(path).parent} ({type(exc).__name__}: {exc})"
    return None


def _verify_document(path: Path, expected: dict[str, Any]) -> str | None:
    """Read *path* back and require it json-equal to *expected*."""
    back, error = _read_document(path)
    if error:
        return f"read-back failed: {error}"
    if _canonical(back) != _canonical(expected):
        return f"{Path(path).name} does not read back json-equal to what was written"
    return None


def _read_pad(local_path: Path) -> tuple[dict[str, Any] | None, list[Any] | None, str | None]:
    """The pad document and its todos list, or a refusal."""
    data, error = _read_document(local_path)
    if error or data is None:
        return None, None, f"pad unreadable: {error}"
    todos = data.get("todos", [])
    if not isinstance(todos, list):
        return None, None, f"'todos' in {Path(local_path).name} is a {type(todos).__name__}, not a list"
    return data, todos, None


# =============================================================================
# THE BACKLOG
# =============================================================================


def _shape_problem(document: dict[str, Any]) -> str | None:
    """Why *document* is not a backlog, or None."""
    if not isinstance(document.get("document_metadata"), dict):
        return "has no document_metadata object"
    if not isinstance(document.get("entries"), list):
        return "has no entries list"
    return None


def read_backlog(backlog_path: Path) -> dict[str, Any]:
    """Read one branch's backlog, answering a missing file honestly.

    Args:
        backlog_path: The backlog file.

    Returns:
        ``{"path", "exists", "document", "entries", "error", "message"}``.
        A missing file is ``exists: False`` with a ``message`` and NO error -
        ``.backup/`` is gitignored, so a fresh clone has none. An unreadable or
        misshapen file carries ``error`` and is never written over.
    """
    path = Path(backlog_path)
    state: dict[str, Any] = {
        "path": path,
        "exists": False,
        "document": None,
        "entries": [],
        "error": None,
        "message": None,
    }
    if not path.exists():
        state["message"] = (
            f"no backlog at {path} - nothing has rolled off this pad on this machine "
            f"({BACKUP_DIR}/ is gitignored, so a fresh clone starts without one)"
        )
        return state

    state["exists"] = True
    document, error = _read_document(path)
    problem = error if document is None else _shape_problem(document)
    if document is None or problem:
        logger.error(f"[todo_roll] Backlog {path} refused: {problem}")
        state["error"] = f"backlog at {path} is unusable ({problem}) - fix or move it aside; it is never written over"
        return state

    state["document"] = document
    state["entries"] = document["entries"]
    return state


def _verify_backlog(
    path: Path, expected: list[Any], originals: list[Any], metadata: dict[str, Any] | None = None
) -> str | None:
    """Read the backlog back: *metadata* (``high_water`` with it), every record, every appended ``entry``."""
    back = read_backlog(path)
    if back["error"] or not back["exists"]:
        return back["error"] or "the file is gone"
    if metadata is not None and _canonical(back["document"]["document_metadata"]) != _canonical(metadata):
        return "document_metadata (high_water) does not read back as written"
    entries = back["entries"]
    if len(entries) != len(expected):
        return f"expected {len(expected)} records, read back {len(entries)}"
    for index, (got, want) in enumerate(zip(entries, expected, strict=True)):
        if _canonical(got) != _canonical(want):
            return f"record {index} does not read back as written"
    offset = len(expected) - len(originals)
    for index, original in enumerate(originals):
        got = entries[offset + index]
        if not isinstance(got, dict) or _canonical(got.get("entry")) != _canonical(original):
            return f"rolled todo {index + 1} of {len(originals)} is not json-equal to the pad's copy"
    return None


def append_to_backlog(
    backlog_path: Path, branch_dir: str, todos: list[Any], reason: str, *, pad: list[Any] | None = None
) -> dict[str, Any]:
    """Append todos to a backlog: append, raise ``high_water``, replace atomically, read back, compare.

    The push rule (row 3) and :func:`roll_todos` both go through here, and
    both prune the pad only after this returns ``success``.

    Args:
        backlog_path: The backlog file.
        branch_dir: The branch directory name stamped into a new backlog.
        todos: The todos to append, in order. Each is stored json-equal under ``entry``.
        reason: One of :data:`REASONS`.
        pad: The whole pad as it stands before the prune; its numbers reach ``high_water``.

    Returns:
        ``{"success", "appended", "path", "error"}``. On failure the pad must
        not be touched.
    """
    path = Path(backlog_path)
    result: dict[str, Any] = {"success": False, "appended": 0, "path": path, "error": None}
    if reason not in REASONS:
        result["error"] = f"unknown roll reason '{reason}' - one of {', '.join(REASONS)}"
        return result
    if not todos:
        result["success"] = True
        return result

    current = read_backlog(path)
    if current["error"]:
        result["error"] = current["error"]
        return result
    document = (
        copy.deepcopy(current["document"])
        if current["exists"]
        else {
            "document_metadata": {"managed_by": MANAGED_BY, "branch": branch_dir},
            "entries": [],
        }
    )
    owner = document["document_metadata"].get("branch")
    if owner is not None and owner != branch_dir:
        result["error"] = f"backlog at {path} belongs to '{owner}', not '{branch_dir}' - refused"
        return result

    rolled = datetime.now().astimezone().isoformat(timespec="seconds")
    records = [{"rolled": rolled, "reason": reason, "entry": copy.deepcopy(todo)} for todo in todos]
    expected = document["entries"] + records
    document["entries"] = expected
    _stamp_high_water(document, todos if pad is None else pad)

    failure = _ensure_parent(path) or _write_document(path, document)
    if failure:
        result["error"] = f"backlog NOT written at {path}: {failure}"
        return result
    mismatch = _verify_backlog(path, expected, todos, document["document_metadata"])
    if mismatch:
        logger.error(f"[todo_roll] Backlog read-back failed at {path}: {mismatch}")
        result["error"] = f"backlog read-back failed at {path}: {mismatch}"
        return result

    result["success"] = True
    result["appended"] = len(records)
    return result


# =============================================================================
# ROLL / RESTORE / NEXT NUMBER
# =============================================================================


def roll_todos(
    branch: str,
    *,
    local_path: Path | None = None,
    backlog_path: Path | None = None,
    backup_root: Path | None = None,
    fleet: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Roll ONE branch's overflow todos, oldest by number, to its backlog.

    Order: backlog append -> atomic replace -> read back and compare every
    record -> only then the pruned pad (atomic, read back). Nothing is
    written when the pad is within its count.

    Args:
        branch: Branch directory name (``@`` optional).
        local_path: Explicit pad file (a scratch copy); skips registry resolution.
        backlog_path: Explicit backlog file.
        backup_root: ``.backup`` override when the backlog path is derived.
        fleet: Scope rows for registry resolution.

    Returns:
        ``{"success", "branch", "count", "pad_before", "pad_after", "rolled",
        "numbers", "backlog", "backlog_display", "error"}``.
    """
    target = _locate(branch, local_path, backlog_path, backup_root, fleet)
    result: dict[str, Any] = {
        "success": False,
        "branch": target["name"],
        "count": None,
        "pad_before": None,
        "pad_after": None,
        "rolled": 0,
        "numbers": [],
        "backlog": target["backlog"],
        "backlog_display": target["backlog_display"],
        "error": None,
    }
    if target["name"] is None:
        result["error"] = target["error"] or target["reason"]
        return result

    count, problem = _pad_count(target["name"])
    data, todos, pad_problem = _read_pad(target["local"])
    if count is None or data is None or todos is None:
        result["error"] = problem or pad_problem
        return result
    result.update(count=count, pad_before=len(todos), pad_after=len(todos))
    if len(todos) <= count:
        result["success"] = True
        return result

    ranked = sorted(range(len(todos)), key=lambda index: _age(todos[index], index))
    rolled_indices = ranked[: len(todos) - count]
    rolled = [todos[index] for index in rolled_indices]
    kept = [todo for index, todo in enumerate(todos) if index not in set(rolled_indices)]

    appended = append_to_backlog(target["backlog"], target["name"], rolled, REASON_OVERFLOW, pad=todos)
    if not appended["success"]:
        result["error"] = f"NOTHING PRUNED - {appended['error']}"
        return result

    pruned = dict(data)
    pruned["todos"] = kept
    failure = _write_document(target["local"], pruned) or _verify_document(target["local"], pruned)
    if failure:
        logger.error(f"[todo_roll] @{target['name']} pad not verified after the backlog took {len(rolled)}: {failure}")
        result["error"] = (
            f"{len(rolled)} todo(s) are in the backlog but the pad was NOT verified pruned ({failure}) - "
            "they are in both places, never in neither"
        )
        return result

    result.update(success=True, rolled=len(rolled), numbers=[_number_of(t) for t in rolled], pad_after=len(kept))
    logger.info(f"[todo_roll] @{target['name']} rolled {len(rolled)} todo(s) to {target['backlog']}")
    json_handler.log_operation(
        "roll_todos",
        {"branch": target["name"], "rolled": len(rolled), "pad_after": len(kept), "count": count},
        module_name=MODULE_NAME,
    )
    return result


def _find_record(entries: list[Any], number: int, path: Path) -> tuple[int | None, str | None]:
    """The one backlog record whose original number is *number*, or a refusal naming the candidates."""
    hits = [
        index
        for index, record in enumerate(entries)
        if isinstance(record, dict) and _number_of(record.get("entry")) == number
    ]
    if not hits:
        return None, f"no todo #{number} in the backlog at {path}"
    if len(hits) > 1:
        named = "; ".join(_candidate(entries[index]) for index in hits)
        return None, f"todo #{number} is ambiguous - {len(hits)} backlog records carry it: {named}. Nothing restored"
    return hits[0], None


def _candidate(record: dict[str, Any]) -> str:
    """One ambiguity candidate as 'rolled <timestamp>: <task>'."""
    entry = record.get("entry")
    task = entry.get("task") if isinstance(entry, dict) else None
    return f"rolled {record.get('rolled', '?')}: {task if isinstance(task, str) else '(no task)'}"


def restore_todo(
    branch: str,
    number: int,
    *,
    local_path: Path | None = None,
    backlog_path: Path | None = None,
    backup_root: Path | None = None,
    fleet: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Move ONE todo from the backlog back onto the TOP of the pad under a fresh number.

    Refused when the pad already holds its configured count, when no record
    carries *number*, or when more than one does (the candidates are named).
    The fresh number is :func:`next_number` with both floors (the backlog's
    ``high_water`` and the pad's rendered ``next #N``), so it is the highest on
    the pad and lands at index 0: lists are newest-first. The pad is written
    first (atomic, read back, verified); only then is that one record removed
    from the backlog and ``high_water`` raised to the fresh number (atomic,
    read back). Every field but ``number`` is carried json-equal.

    Args:
        branch: Branch directory name (``@`` optional).
        number: The todo's ORIGINAL number as it sits in the backlog.
        local_path: Explicit pad file (a scratch copy); skips registry resolution.
        backlog_path: Explicit backlog file.
        backup_root: ``.backup`` override when the backlog path is derived.
        fleet: Scope rows for registry resolution.

    Returns:
        ``{"success", "branch", "original_number", "number", "task", "pad",
        "count", "backlog", "error"}``.
    """
    target = _locate(branch, local_path, backlog_path, backup_root, fleet)
    result: dict[str, Any] = {
        "success": False,
        "branch": target["name"],
        "original_number": number,
        "number": None,
        "task": None,
        "pad": None,
        "count": None,
        "backlog": target["backlog"],
        "error": None,
    }
    if target["name"] is None:
        result["error"] = target["error"] or target["reason"]
        return result
    if isinstance(number, bool) or not isinstance(number, int):
        result["error"] = f"a todo number is a whole number, got {number!r}"
        return result

    count, problem = _pad_count(target["name"])
    data, todos, pad_problem = _read_pad(target["local"])
    if count is None or data is None or todos is None:
        result["error"] = problem or pad_problem
        return result
    result.update(pad=len(todos), count=count)
    if len(todos) >= count:
        result["error"] = f"pad is full ({len(todos)}/{count}) - finish or delete one before restoring #{number}"
        return result

    backlog = read_backlog(target["backlog"])
    if backlog["error"] or not backlog["exists"]:
        result["error"] = backlog["error"] or backlog["message"]
        return result
    index, problem = _find_record(backlog["entries"], number, target["backlog"])
    if index is None:
        result["error"] = problem
        return result

    record = backlog["entries"][index]
    fresh = next_number(
        todos,
        backlog["entries"],
        high_water=high_water_of(backlog["document"]),
        tab_floor=floor_from_tab(data.get("todos_meta")),
    )
    restored = {key: (fresh if key == "number" else copy.deepcopy(value)) for key, value in record["entry"].items()}
    pad = dict(data)
    pad["todos"] = [restored] + list(todos)
    failure = _write_document(target["local"], pad) or _verify_document(target["local"], pad)
    if failure:
        result["error"] = f"NOTHING RESTORED - the pad was not verified ({failure}); the backlog is untouched"
        return result

    remaining = backlog["entries"][:index] + backlog["entries"][index + 1 :]
    document = copy.deepcopy(backlog["document"])
    document["entries"] = remaining
    _stamp_high_water(document, pad["todos"], fresh)
    failure = _write_document(target["backlog"], document) or _verify_backlog(
        target["backlog"], remaining, [], document["document_metadata"]
    )
    if failure:
        logger.error(f"[todo_roll] @{target['name']} #{fresh} restored but backlog record kept: {failure}")
        result["error"] = (
            f"#{number} is on the pad as #{fresh}, but its backlog record was NOT removed ({failure}) - "
            "it is in both places, never in neither"
        )
        return result

    result.update(success=True, number=fresh, task=restored.get("task"), pad=len(todos) + 1)
    json_handler.log_operation(
        "restore_todo",
        {"branch": target["name"], "original_number": number, "number": fresh},
        module_name=MODULE_NAME,
    )
    return result
