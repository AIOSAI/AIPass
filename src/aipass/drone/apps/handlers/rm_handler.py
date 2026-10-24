# =================== AIPass ====================
# Name: rm_handler.py
# Description: Contained safe-delete handler
# Version: 1.4.5
# Created: 2026-06-02
# Modified: 2026-10-23
# =============================================

"""Contained safe-delete handler.

Roots match Codex sandbox boundaries: writable = {project, /tmp, $TMPDIR}.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers import deletion_log
from aipass.drone.apps.handlers.router_handler import caller_cwd, find_project_root
from aipass.drone.apps.handlers.json import json_handler

_CARVEOUT_DIRS = frozenset((".git", ".trinity", ".aipass", ".codex", ".agents"))


def get_allowed_roots() -> list[Path]:
    """Return resolved roots under which deletion is permitted."""
    seen: set[Path] = set()
    roots: list[Path] = []

    project_root = find_project_root()
    if project_root is not None and project_root not in seen:
        seen.add(project_root)
        roots.append(project_root)

    tmp_candidates: list[Path] = []
    if sys.platform != "win32":
        tmp_candidates.append(Path("/tmp"))
    tmp_candidates.append(Path(tempfile.gettempdir()))

    for tmp_candidate in tmp_candidates:
        resolved = tmp_candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    return roots


def _find_branch_root(path: Path, project_root: Path) -> Path | None:
    """Walk up from *path* to the OUTERMOST .trinity/ ancestor within the project.

    Outermost, because a ``.trinity/`` is not proof of a citizen: @spawn's templates hold
    branch skeletons. No ``.trinity/`` exists above a branch, so the outermost hit is the citizen.
    A symlink is never a citizen (its ``.trinity`` is the target's).
    """
    root = project_root.resolve()
    outermost: Path | None = None
    for parent in [path, *path.parents]:
        if not parent.is_relative_to(root):
            break
        if (parent / ".trinity").is_dir() and not parent.is_symlink():
            outermost = parent
    return outermost


def _current_branch_root(project_root: Path | None) -> Path | None:
    """Return the root of the branch the CWD lives in, or None (also when there is no CWD)."""
    if project_root is None:
        return None
    cwd = caller_cwd()
    if cwd is None:
        return None
    return _find_branch_root(cwd.resolve(), project_root)


def check_protected_dirs(resolved: Path) -> tuple[bool, str]:
    """The carve-out half of the fence, apart so stale mode can keep it. Returns ``(blocked, reason)``."""
    for part in resolved.parts:
        if part in _CARVEOUT_DIRS:
            return True, f"Protected directory: path is inside {part}/"
    return False, ""


def check_carveouts(resolved: Path, project_root: Path | None) -> tuple[bool, str]:
    """Refuse deletion of protected paths even inside allowed roots. Returns ``(blocked, reason)``."""
    blocked, reason = check_protected_dirs(resolved)
    if blocked:
        return blocked, reason

    own = _current_branch_root(project_root)
    if project_root is not None:
        target_branch_root = _find_branch_root(resolved, project_root)
        if target_branch_root is not None and target_branch_root != own:
            return True, f"Protected: path is inside sibling branch {target_branch_root.name}/"

    blocked, reason = check_contained_citizens(resolved, project_root, own)
    if not blocked and own is not None and own.is_relative_to(resolved):
        return True, f"Protected: path is your own branch {own.name}/ or holds it"
    return blocked, reason


def check_contained_citizens(resolved: Path, project_root: Path | None, own: Path | None) -> tuple[bool, str]:
    """Refuse a project directory that CONTAINS a citizen other than the caller.

    The sibling fence walks UP, so a target ABOVE the branches (``drone rm ..`` = ``src/aipass/``)
    passes it; this walks DOWN. A target inside a branch, the caller's own branch and symlinks
    are skipped. *own* is the caller's branch root, or None. A folder the walk cannot list refuses.
    Returns ``(blocked, reason)``.
    """
    if project_root is None or not resolved.is_relative_to(project_root) or not resolved.is_dir():
        return False, ""
    if resolved.is_symlink():
        return False, ""
    if _find_branch_root(resolved, project_root) is not None:
        return False, ""

    unreadable: list[OSError] = []
    for dirpath, dirnames, _filenames in os.walk(resolved, onerror=unreadable.append):
        if unreadable:
            break
        here = Path(dirpath)
        dirnames.sort()
        for name in list(dirnames):
            child = here / name
            if child.is_symlink() or not os.path.isdir(child / ".trinity"):
                continue
            if child != own:
                return True, f"Protected: path contains citizen {name}/ ({child}) — another branch's tree"
            dirnames.remove(name)

    if unreadable:
        exc = unreadable[0]
        return True, (
            f"Protected: cannot verify {resolved} holds no citizen — {exc.filename} is unreadable "
            f"({exc.strerror or exc})"
        )
    return False, ""


def check_containment(path: Path, roots: list[Path]) -> tuple[bool, str]:
    """Check if *path* (already resolved) is a strict child of any allowed root.

    Returns ``(allowed, reason)``. Roots may nest, so equality to ANY root is checked first.
    """
    root_set = frozenset(roots)
    if path in root_set:
        return False, f"Refusing to delete root directory itself: {path}"

    for root in roots:
        if path.is_relative_to(root):
            return True, ""

    allowed_str = ", ".join(str(r) for r in roots)
    return False, (f"Path {path} is outside allowed roots.\n  Allowed: {allowed_str}")


def safe_delete(paths: list[str]) -> list[tuple[str, bool, str]]:
    """Delete *paths* with containment checks; a refused path does not block others."""
    return _safe_delete_direct(paths)


def _standing_inside(resolved: Path, cwd: Path | None) -> str:
    """Name the caller's own position when that is what blocked the delete.

    Windows refuses to remove a tree the process stands in (WinError 32); ``drone rm ..`` does that.
    """
    if cwd is None or not cwd.is_relative_to(resolved):
        return ""
    return f" — this process is standing in {cwd}; run drone rm from outside {resolved}"


def _remove_tree(path: Path) -> None:
    """Remove a directory tree in rm's direct lane — where the host answers.

    Its own function so tests/test_rm.py can stand Windows' refusal in for it on POSIX.
    """
    shutil.rmtree(path)


def _safe_delete_direct(paths: list[str]) -> list[tuple[str, bool, str]]:
    """Delete paths directly (unsandboxed mode — current behavior)."""
    roots = get_allowed_roots()
    if not roots:
        return [(p, False, "No allowed roots found (no project registry, no temp dir)") for p in paths]

    project_root = find_project_root()
    json_handler.log_operation("rm", {"paths": paths, "roots": [str(r) for r in roots]})

    results: list[tuple[str, bool, str]] = []
    cwd = caller_cwd()
    for path_str in paths:
        original = Path(path_str)
        if original.is_absolute():
            absolute = original
        elif cwd is not None:
            absolute = cwd / original
        else:
            # Refused per path, so absolute paths in the same call still delete.
            message = f"Cannot resolve relative path '{path_str}' — this process has no current directory"
            results.append((path_str, False, message))
            logger.info("rm: %s", message)
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_REFUSED,
                requested=path_str,
                resolved=original,
                reason=message,
            )
            continue

        exists_on_disk = absolute.exists() or absolute.is_symlink()
        if not exists_on_disk:
            message = f"Path does not exist: {absolute}"
            results.append((path_str, False, message))
            logger.info("rm: nonexistent path %s", absolute)
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_NOT_FOUND,
                requested=path_str,
                resolved=absolute,
                reason=message,
            )
            continue

        # A symlink is judged by where the LINK lives, not its target: only the link is removed.
        target: Path | None = None
        if absolute.is_symlink():
            target = absolute.resolve()
            resolved = absolute.parent.resolve() / absolute.name
        else:
            resolved = absolute.resolve()

        allowed, reason = check_containment(resolved, roots)
        if not allowed:
            results.append((path_str, False, reason))
            logger.warning(
                "rm: containment refused %s (resolved %s): %s",
                path_str,
                resolved,
                reason,
            )
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_REFUSED,
                requested=path_str,
                resolved=resolved,
                reason=reason,
                target=target,
            )
            continue

        blocked, carveout_reason = check_carveouts(resolved, project_root)
        if blocked:
            results.append((path_str, False, carveout_reason))
            logger.warning(
                "rm: carveout refused %s (resolved %s): %s",
                path_str,
                resolved,
                carveout_reason,
            )
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_REFUSED,
                requested=path_str,
                resolved=resolved,
                reason=carveout_reason,
                target=target,
            )
            continue

        measurement = deletion_log.measure(absolute)

        try:
            # Delete the RESOLVED path the guards judged: rmtree("spawn/..") fails its last rmdir.
            if target is not None:
                absolute.unlink()
            elif resolved.is_dir():
                _remove_tree(resolved)
            else:
                resolved.unlink()
            message = f"Deleted: {resolved}" + (f" (symlink to {target})" if target is not None else "")
            results.append((path_str, True, message))
            logger.info("rm: deleted %s (resolved %s)", path_str, resolved)
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_DELETED,
                requested=path_str,
                resolved=resolved,
                reason=message,
                measurement=measurement,
                target=target,
            )
        except Exception as exc:
            message = f"Delete failed: {exc}{_standing_inside(resolved, cwd)}"
            results.append((path_str, False, message))
            logger.error("rm: delete failed for %s: %s", path_str, exc)
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_FAILED,
                requested=path_str,
                resolved=resolved,
                reason=message,
                measurement=measurement,
                target=target,
            )

    return results


MODE_STALE = "stale"
STALE_FLAG = "--stale"
DRY_RUN_FLAG = "--dry-run"

_STALE_FILE_SUFFIX = ".tmp"
_STALE_FOLDER_SUFFIX = "_json"

_AGE_UNITS = {"d": 86_400, "h": 3_600, "m": 60}
_AGE_FORMS = "10d (days), 36h (hours) or 90m (minutes)"
# [0-9], not \d: \d matches every Unicode digit and int() reads them all.
_AGE_PATTERN = re.compile(r"([0-9]+)([dhm])")


@dataclass(frozen=True)
class StaleRequest:
    """One parsed ``--stale`` invocation."""

    age: str
    age_seconds: int
    dry_run: bool
    dirs: tuple[str, ...]


@dataclass
class StaleReport:
    """What one sweep saw and did. The summary line is rendered from this."""

    folders_scanned: int = 0
    matched: int = 0
    matched_bytes: int = 0
    deleted: int = 0
    freed_bytes: int = 0
    candidates: list[tuple[Path, float, int]] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)


def is_stale_request(tokens: list[str]) -> bool:
    """True when any token asks for stale mode — in ANY slot, in any spelling.

    The plain lane reads every token as a path: ``drone rm api_json --stale 10d`` there removes the folder.
    """
    return any(token.startswith(STALE_FLAG) for token in tokens)


def parse_age(text: str) -> int:
    """Seconds in a stale-mode AGE: ``10d``, ``36h`` or ``90m``.

    Zero is refused: it matches a staged write in flight, and unlinking its temp fails the rename.
    """
    match = _AGE_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"Invalid age '{text}' — use a whole number and a unit: {_AGE_FORMS}")
    amount = int(match.group(1))
    if amount == 0:
        raise ValueError(f"Invalid age '{text}' — zero would match a write in flight; use {_AGE_FORMS}")
    return amount * _AGE_UNITS[match.group(2)]


def parse_stale_args(tokens: list[str]) -> StaleRequest:
    """Parse ``--stale AGE [--dry-run] DIR [DIR...]``, flags in any slot.

    Raises ValueError before any walk on an unknown ``-`` token: a mistyped ``--dry-run`` read as
    a DIR would turn a rehearsal into a sweep.
    """
    flags = [i for i, token in enumerate(tokens) if token.startswith(STALE_FLAG)]
    if len(flags) != 1:
        raise ValueError(f"Stale mode takes exactly one {STALE_FLAG} AGE — nothing was deleted")
    index = flags[0]
    flag = tokens[index]
    if flag == STALE_FLAG:
        if index + 1 >= len(tokens):
            raise ValueError(f"{STALE_FLAG} needs an age: {_AGE_FORMS}")
        age = tokens[index + 1]
        rest = tokens[:index] + tokens[index + 2 :]
    elif flag.startswith(STALE_FLAG + "="):
        age = flag[len(STALE_FLAG) + 1 :]
        rest = tokens[:index] + tokens[index + 1 :]
    else:
        raise ValueError(f"Unknown option '{flag}' — did you mean {STALE_FLAG} AGE? Nothing was deleted")
    age_seconds = parse_age(age)

    dirs = tuple(token for token in rest if token != DRY_RUN_FLAG)
    unknown = [token for token in dirs if token.startswith("-")]
    if unknown:
        raise ValueError(f"Unknown option(s) in stale mode: {' '.join(unknown)} — nothing was deleted")
    if not dirs:
        raise ValueError(f"{STALE_FLAG} {age} needs at least one DIR to sweep")
    return StaleRequest(age=age, age_seconds=age_seconds, dry_run=DRY_RUN_FLAG in rest, dirs=dirs)


def format_age(seconds: float) -> str:
    """Render an age as ``11d3h``, ``5h20m`` or ``42m`` — two units at most."""
    minutes = int(seconds // 60)
    days, remainder = divmod(minutes, 1_440)
    hours, mins = divmod(remainder, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{mins}m"
    return f"{mins}m"


def format_stale_summary(request: StaleRequest, report: StaleReport) -> str:
    """The one summary line every stale run ends with, dry or real."""
    run = "dry run" if request.dry_run else "swept"
    return (
        f"rm --stale {request.age} ({run}): folders scanned {report.folders_scanned}, "
        f"files matched {report.matched} ({report.matched_bytes} bytes), "
        f"files deleted {report.deleted}, bytes freed {report.freed_bytes}, "
        f"refusals {len(report.refusals)}"
    )


def stale_sweep(request: StaleRequest) -> StaleReport:
    """Walk each DIR and unlink the staging temps older than the request's age.

    A candidate is a regular ``*.tmp`` file directly in a ``*_json`` folder, older than the age.
    The walk skips carve-outs, dropbox and .archive, but a DIR the user names inside one is swept.
    The sibling-branch fence is crossed here only: a stale temp is no citizen's work, and one
    weekly job sweeps every branch. A dry run records nothing; its refusals still count.
    """
    report = StaleReport()
    json_handler.log_operation(
        "rm_stale",
        {"dirs": list(request.dirs), "age": request.age, "dry_run": request.dry_run},
    )
    project_root = find_project_root()
    cwd = caller_cwd()
    now = time.time()
    visited: set[Path] = set()
    for dir_arg in request.dirs:
        root = _resolve_stale_dir(request, dir_arg, project_root, cwd, report)
        if root is None:
            continue
        for path, age, size in _find_stale(root, request.age_seconds, now, visited, report):
            report.matched += 1
            report.matched_bytes += size
            report.candidates.append((path, age, size))
            if not request.dry_run:
                _unlink_stale(request, dir_arg, path, age, size, report)
    logger.info("rm --stale: %s", format_stale_summary(request, report))
    return report


def _resolve_stale_dir(
    request: StaleRequest,
    dir_arg: str,
    project_root: Path | None,
    cwd: Path | None,
    report: StaleReport,
) -> Path | None:
    """Resolve and fence one DIR: return it resolved, or refuse it and return None."""
    original = Path(dir_arg)
    if project_root is None:
        message = "No project root found — stale mode sweeps inside a project only"
        return _refuse_stale_dir(request, dir_arg, original, deletion_log.OUTCOME_REFUSED, message, report)
    if not original.is_absolute():
        if cwd is None:
            message = f"Cannot resolve relative path '{dir_arg}' — this process has no current directory"
            return _refuse_stale_dir(request, dir_arg, original, deletion_log.OUTCOME_REFUSED, message, report)
        original = cwd / original
    if not (original.exists() or original.is_symlink()):
        message = f"Path does not exist: {original}"
        return _refuse_stale_dir(request, dir_arg, original, deletion_log.OUTCOME_NOT_FOUND, message, report)

    resolved = original.resolve()
    allowed, reason = check_containment(resolved, [project_root])
    if not allowed:
        return _refuse_stale_dir(request, dir_arg, resolved, deletion_log.OUTCOME_REFUSED, reason, report)
    blocked, reason = check_protected_dirs(resolved)
    if blocked:
        return _refuse_stale_dir(request, dir_arg, resolved, deletion_log.OUTCOME_REFUSED, reason, report)
    if not resolved.is_dir():
        message = f"Not a directory: {resolved} — stale mode sweeps directories"
        return _refuse_stale_dir(request, dir_arg, resolved, deletion_log.OUTCOME_REFUSED, message, report)
    return resolved


def _refuse_stale_dir(
    request: StaleRequest,
    dir_arg: str,
    resolved: Path,
    outcome: str,
    message: str,
    report: StaleReport,
) -> None:
    """Count, log and (unless dry) record one refused DIR."""
    report.refusals.append(message)
    logger.warning("rm --stale: refused %s: %s", dir_arg, message)
    if not request.dry_run:
        deletion_log.record_deletion(
            lane=deletion_log.LANE_RM,
            outcome=outcome,
            requested=dir_arg,
            resolved=resolved,
            reason=message,
            mode=MODE_STALE,
            age=request.age,
        )
    return None


def _find_stale(
    root: Path,
    age_seconds: int,
    now: float,
    visited: set[Path],
    report: StaleReport,
) -> list[tuple[Path, float, int]]:
    """Every candidate under *root* as ``(path, age in seconds, size in bytes)``.

    *visited* is shared across one run's DIRs, so overlapping DIRs never match a file twice.
    """
    found: list[tuple[Path, float, int]] = []

    def _unreadable(exc: OSError) -> None:
        # os.walk's default skips what it cannot list in silence; a sweep that did not look is not clean.
        message = f"Cannot scan {exc.filename}: {exc.strerror or exc}"
        report.refusals.append(message)
        logger.warning("rm --stale: %s", message)

    for dirpath, dirnames, filenames in os.walk(root, onerror=_unreadable):
        here = Path(dirpath)
        if here in visited:
            dirnames.clear()
            continue
        visited.add(here)
        report.folders_scanned += 1
        dirnames[:] = [name for name in dirnames if name not in _CARVEOUT_DIRS and name not in (".archive", "dropbox")]
        if not here.name.endswith(_STALE_FOLDER_SUFFIX):
            continue
        for name in filenames:
            if not name.endswith(_STALE_FILE_SUFFIX):
                continue
            path = here / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                logger.debug("rm --stale: %s vanished before it could be read", path)
                continue
            except OSError as exc:
                _unreadable(exc)
                continue
            age = now - info.st_mtime
            if stat.S_ISREG(info.st_mode) and age > age_seconds:
                found.append((path, age, info.st_size))
    return found


def _unlink_stale(
    request: StaleRequest,
    dir_arg: str,
    path: Path,
    age: float,
    size: int,
    report: StaleReport,
) -> None:
    """Unlink one candidate and record what happened — deleted, or why not."""
    measurement = deletion_log.measure(path)
    try:
        path.unlink()
    except OSError as exc:
        outcome = deletion_log.OUTCOME_NOT_FOUND if isinstance(exc, FileNotFoundError) else deletion_log.OUTCOME_FAILED
        reason = f"Delete failed: {exc}"
        report.refusals.append(reason)
        logger.error("rm --stale: delete failed for %s: %s", path, exc)
    else:
        outcome = deletion_log.OUTCOME_DELETED
        reason = f"Stale staging temp, {format_age(age)} old (limit {request.age})"
        report.deleted += 1
        report.freed_bytes += size
    deletion_log.record_deletion(
        lane=deletion_log.LANE_RM,
        outcome=outcome,
        requested=dir_arg,
        resolved=path,
        reason=reason,
        measurement=measurement,
        mode=MODE_STALE,
        age=request.age,
    )
