# =================== AIPass ====================
# Name: todo_roll.py
# Description: Todo pad roll-off to .backup/todo/<branch>/backlog.json, file only, verified before the pad is pruned
# Version: 1.5.0
# Created: 2026-09-15
# Modified: 2026-10-17
# =============================================

"""Todo Roll Handler (DPLAN-0345 row 1, FPLAN-0590)

FILE ONLY, never vectorized: a vectorized rolled todo duplicates on restore then re-roll.
THE ORDER IS THE CONTRACT: append the backlog, replace atomically, read back json-equal,
and only then write the pruned pad. A todo may sit in both places, never in neither.
OWN BRANCH ONLY: nothing on the detached fleet walk calls this module.
Reference: docs/todos_and_backlog.md
"""

import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from aipass.prax import logger
from aipass.memory.apps.handlers import repo_root, write_fence
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json.entry_limits import check_entry_shape, load_entry_limits
from aipass.memory.apps.handlers.json.memory_files import read_memory_file, violation_line, write_memory_file
from aipass.memory.apps.handlers.monitor import registry_scope

MODULE_NAME = "todo_roll"

BACKUP_DIR = ".backup"
TODO_DIR = "todo"
BACKLOG_FILE = "backlog.json"
# Records past the ceiling move here, never deleted: the backlog is a rolled todo's only copy.
ARCHIVE_FILE = "backlog.archive.json"
MANAGED_BY = "memory"
TRINITY_DIR = ".trinity"
LOCAL_FILE = "local.json"

# As memory.config.json spells them: a typo finds no rules and passes an illegal entry clean.
TODO_TYPE = "todos"
TODO_CONTAINER = "todos"

REASON_OVERFLOW = "overflow"
REASON_NON_CANONICAL = "non-canonical"
REASON_MIGRATION = "migration"
REASONS = (REASON_OVERFLOW, REASON_NON_CANONICAL, REASON_MIGRATION)

HIGH_WATER_KEY = "high_water"

# Only tab_renderer._todos_tab's "· next #N ⟧" shape is read; anything else is no floor.
_TAB_NEXT_RE = re.compile(r"⟦ [^⟧]* · next #([1-9][0-9]*) ⟧")

# BRANCH_NAME without CALLER_CWD: the launcher picked the process cwd, so it says nothing.
# AIPASS_CALLER_BRANCH is never read: at a repo root drone stamps the PROJECT name there.
CALLER_CWD_VAR = "AIPASS_CALLER_CWD"
BRANCH_NAME_VAR = "AIPASS_BRANCH_NAME"


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
    """The ``document_metadata.high_water`` a backlog carries, or None (no floor, never an error)."""
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
    """The next todo number: one past the highest number memory can see for the branch."""
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


def backlog_path_for(branch_dir: str, backup_root: Path | None = None) -> Path:
    """The backlog file for one branch DIRECTORY name (not the registry name)."""
    root = Path(backup_root) if backup_root is not None else _find_repo_root() / BACKUP_DIR
    return root / TODO_DIR / branch_dir / BACKLOG_FILE


def in_scope_branches(root: Path | None = None) -> list[dict[str, Any]]:
    """Core citizens and passport-declared residents, named by directory; no external tier (this lane writes).

    strict: without the core rows a resident sharing a citizen's directory name would win the backlog path.
    """
    base = Path(root) if root is not None else _find_repo_root()
    return [
        item
        for item in registry_scope.fleet_branches(base, name_from="path", strict=True)
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
    """Where the caller stood, or ``(None, reason)`` when there is no evidence."""
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
    """Resolve the ONE branch a todo operation acts on; *branch* None means the caller's cwd branch."""
    if fleet is not None:
        scope = list(fleet)
    else:
        try:
            scope = in_scope_branches()
        except registry_scope.RegistryUnreadable as exc:
            logger.error(f"[todo_roll] REFUSED: {exc}")
            return _no_target(error=f"REFUSED: {exc}")

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
    """Atomic write through ``memory_files.write_memory_file``; the refusal, or None."""
    result = write_memory_file(Path(path), document)
    if result.get("success"):
        return None
    return str(result.get("error") or "the memory-file writer refused without a reason")


def _ensure_parent(path: Path) -> str | None:
    """Create *path*'s directory; returns the failure, or None. Never outside the AIPass root."""
    refusal = write_fence.fence_write(path, lane="todo_roll")
    if refusal is not None:
        return refusal
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


def _shape_problem(document: dict[str, Any]) -> str | None:
    """Why *document* is not a backlog, or None."""
    if not isinstance(document.get("document_metadata"), dict):
        return "has no document_metadata object"
    if not isinstance(document.get("entries"), list):
        return "has no entries list"
    return None


def read_backlog(backlog_path: Path) -> dict[str, Any]:
    """Read one branch's backlog; a missing file is a state (``.backup/`` is gitignored), not an error."""
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

    Callers (the push, :func:`roll_todos`) prune the pad only after ``success``.
    """
    path = Path(backlog_path)
    result: dict[str, Any] = {"success": False, "appended": 0, "archived": 0, "path": path, "error": None}
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

    # A failed trim never fails the append: the records are on disk and the caller prunes on that.
    trimmed = trim_backlog(path, branch_dir)
    result["archived"] = trimmed["archived"]
    if not trimmed["success"]:
        logger.warning(f"[todo_roll] @{branch_dir} appended {len(records)}, backlog not trimmed: {trimmed['error']}")
    return result


def archive_path_for(backlog_path: Path) -> Path:
    """The archive file that sits beside *backlog_path*."""
    return Path(backlog_path).with_name(ARCHIVE_FILE)


def trim_backlog(backlog_path: Path, branch_dir: str, *, ceiling: int | None = None) -> dict[str, Any]:
    """Move the OLDEST records (file order) past *ceiling* out of the backlog and into its archive.

    Same order as the roll: archive written and verified before the backlog shortens.
    ``high_water`` is not lowered. ``todo restore`` reads the backlog only, never the archive.
    Config ``None`` means NO TRIM, never a trim to zero.
    """
    path = Path(backlog_path)
    archive = archive_path_for(path)
    result: dict[str, Any] = {"success": True, "archived": 0, "kept": None, "archive": archive, "error": None}

    keep = config_loader.get_backlog_ceiling() if ceiling is None else ceiling
    if keep is None or isinstance(keep, bool) or not isinstance(keep, int) or keep < 1:
        return result

    current = read_backlog(path)
    if current["error"] or not current["exists"]:
        result["kept"] = 0 if not current["exists"] else None
        if current["error"]:
            result["success"] = False
            result["error"] = current["error"]
        return result

    entries = list(current["entries"])
    result["kept"] = len(entries)
    if len(entries) <= keep:
        return result

    overflow = entries[: len(entries) - keep]
    kept = entries[len(entries) - keep :]

    stored = read_backlog(archive)
    if stored["error"]:
        result.update(success=False, error=f"archive unreadable at {archive}: {stored['error']}")
        return result
    document = (
        copy.deepcopy(stored["document"])
        if stored["exists"]
        else {"document_metadata": {"managed_by": MANAGED_BY, "branch": branch_dir}, "entries": []}
    )
    owner = document["document_metadata"].get("branch")
    if owner is not None and owner != branch_dir:
        result.update(success=False, error=f"archive at {archive} belongs to '{owner}', not '{branch_dir}' - refused")
        return result

    expected = document["entries"] + overflow
    document["entries"] = expected
    failure = _ensure_parent(archive) or _write_document(archive, document)
    if failure:
        result.update(success=False, error=f"NOTHING TRIMMED - archive not written at {archive}: {failure}")
        return result
    mismatch = _verify_backlog(archive, expected, [], document["document_metadata"])
    if mismatch:
        logger.error(f"[todo_roll] Archive read-back failed at {archive}: {mismatch}")
        result.update(success=False, error=f"NOTHING TRIMMED - archive read-back failed at {archive}: {mismatch}")
        return result

    shortened = copy.deepcopy(current["document"])
    shortened["entries"] = kept
    failure = _write_document(path, shortened) or _verify_backlog(
        path, kept, [], shortened.get("document_metadata", {})
    )
    if failure:
        logger.error(f"[todo_roll] @{branch_dir} {len(overflow)} record(s) archived, backlog not shortened: {failure}")
        result.update(
            success=False,
            archived=len(overflow),
            error=(
                f"{len(overflow)} record(s) are in the archive but the backlog was NOT shortened ({failure}) - "
                "they are in both files, never in neither"
            ),
        )
        return result

    result.update(archived=len(overflow), kept=len(kept))
    logger.info(f"[todo_roll] @{branch_dir} archived {len(overflow)} backlog record(s) past {keep} to {archive}")
    json_handler.log_operation(
        "trim_backlog",
        {"branch": branch_dir, "archived": len(overflow), "kept": len(kept), "ceiling": keep},
        module_name=MODULE_NAME,
    )
    return result


def roll_todos(
    branch: str,
    *,
    local_path: Path | None = None,
    backlog_path: Path | None = None,
    backup_root: Path | None = None,
    fleet: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Roll ONE branch's overflow todos, oldest by number, to its backlog; nothing written within count."""
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


def _rendered_todos_meta(
    branch_dir: str, pad: list[Any], backlog: dict[str, Any], todos_meta: Any
) -> tuple[str | None, str | None]:
    """The ``todos_meta`` line memory's renderer writes for *pad*, or ``(None, refusal)``.

    Imported at call time: tab_renderer imports this module at its top.
    """
    from aipass.memory.apps.handlers.tracking import tab_renderer

    config = config_loader.load()
    context = tab_renderer.todo_context(branch_dir, pad, backlog, todos_meta=todos_meta)
    try:
        meta = tab_renderer.compose_meta(
            "todos", config.get("rollover", {}), config.get("entry_limits", {}), branch_dir, context
        )
    except (OSError, ValueError) as exc:
        logger.error(f"[todo_roll] @{branch_dir} todos tab not rendered: {type(exc).__name__}: {exc}")
        return None, f"the todos tab could not be rendered ({type(exc).__name__}: {exc})"
    return meta, None


def shape_problems(entry: Any, branch: str) -> list[str]:
    """Every way *entry* sits outside the todo shape, one readable line per rule. Reports only.

    Rules and sentences come from the write gate's own code, so the pre-flight cannot disagree with it.
    """
    limits = load_entry_limits(branch)
    hits = check_entry_shape(TODO_TYPE, TODO_CONTAINER, "0", entry, limits)
    return [violation_line(hit) for hit in hits]


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

    Lists are newest-first, so the fresh (highest) number lands at index 0. The pad, with a
    re-rendered ``todos_meta``, is written and verified before the backlog record is removed.
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

    problems = shape_problems(restored, target["name"])
    if problems:
        result["error"] = (
            f"NOTHING RESTORED - #{number} is not the shape a todo may take: {'; '.join(problems)}. "
            "The backlog is the only copy of it and is never reshaped by this verb, so the record stays "
            "exactly as it is; the pad and the backlog are untouched. Write the work onto your pad as a "
            "new todo in the shape above - the backlog keeps the original"
        )
        logger.warning(f"[todo_roll] @{target['name']} restore #{number} refused pre-write: {'; '.join(problems)}")
        return result

    pad = dict(data)
    pad["todos"] = [restored] + list(todos)
    meta, problem = _rendered_todos_meta(target["name"], pad["todos"], backlog, data.get("todos_meta"))
    if meta is None:
        result["error"] = f"NOTHING RESTORED - {problem}; the pad and the backlog are untouched"
        return result
    pad["todos_meta"] = meta
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
