# =================== AIPass ====================
# Name: rm_handler.py
# Description: Contained safe-delete handler
# Version: 1.4.0
# Created: 2026-06-02
# Modified: 2026-09-11
# =============================================

"""Contained safe-delete handler.

Deletes paths using shutil.rmtree (directories) or Path.unlink (files),
constrained to project root and system temp directories. Provider-agnostic
alternative to shell ``rm``.

Matches Codex sandbox boundaries: writable = {project, /tmp, $TMPDIR}.
Hard carve-outs protect .git, .trinity, .aipass, .codex, .agents, sibling
branch worktrees, and any project directory that CONTAINS another citizen,
even inside allowed roots.

Stale mode (``--stale AGE``, DPLAN-0338) is a second, narrower lane: it walks
directories and unlinks only staging temps — ``*.tmp`` regular files directly
inside a ``*_json`` folder, older than AGE. It keeps the carve-outs and crosses
the sibling-branch fence; see :func:`stale_sweep` for why.
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
from aipass.drone.apps.handlers.router_handler import caller_cwd, registries_in
from aipass.drone.apps.handlers.json import json_handler

_CARVEOUT_DIRS = frozenset((".git", ".trinity", ".aipass", ".codex", ".agents"))


def _find_project_root() -> Path | None:
    """Walk up from CWD to find *_REGISTRY.json; return its parent as project root.

    THE LIVE ONE. @trigger reproduced this: delete the directory you are standing
    in, then run a second ``drone rm`` to clean up — the recovery command is the
    one that crashed here, exit 1, before any of the delete lane's own guards ran.
    The walk is skipped when there is nowhere to walk from; AIPASS_HOME answers
    without a location and always could have.
    """
    cwd = caller_cwd()
    if cwd is not None:
        for parent in [cwd, *cwd.parents]:
            if registries_in(parent):
                return parent.resolve()
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        home = Path(aipass_home)
        if home.is_dir() and registries_in(home):
            return home.resolve()
    return None


def get_allowed_roots() -> list[Path]:
    """Return resolved roots under which deletion is permitted.

    Union of: project root, system temp dir, and (on POSIX) the canonical
    temp path.  Deduplicated by resolved path.
    """
    seen: set[Path] = set()
    roots: list[Path] = []

    project_root = _find_project_root()
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

    Outermost, not innermost, because a ``.trinity/`` is not proof of a citizen.
    @spawn ships a complete branch skeleton under ``templates/`` — passport and
    all — so the innermost hit for
    ``spawn/templates/aipass_framework/.pytest_cache`` was the skeleton, and the
    guard refused with "sibling branch aipass_framework/", naming something that
    is not a citizen and has no mailbox to appeal to. It also locked @spawn out
    of its own templates: the skeleton's name never matches the branch you are
    standing in, so every path in there read as somebody else's home.

    Outermost-wins is the same mapping @devpulse used to fix the commit gate
    (e934099f) when the identical mimicry made it run pytest inside the
    template. One rule for one bug, not two rules for two symptoms.

    Safe because no ``.trinity/`` exists above a branch: not at the project
    root, not at ``src/``, not at ``src/aipass/``. The outermost hit inside the
    project IS the citizen. The walk stops at the project boundary, so a
    ``.trinity`` outside it can never claim a path inside.
    """
    root = project_root.resolve()
    outermost: Path | None = None
    for parent in [path, *path.parents]:
        if not parent.is_relative_to(root):
            break
        if (parent / ".trinity").is_dir():
            outermost = parent
    return outermost


def _current_branch_root(project_root: Path | None) -> Path | None:
    """Return the root of the branch the CWD lives in, or None.

    Already Optional, and "no CWD" is one more way the answer is unknown — the
    branch is inferred from where the caller stands, not from who they are.
    """
    if project_root is None:
        return None
    cwd = caller_cwd()
    if cwd is None:
        return None
    return _find_branch_root(cwd.resolve(), project_root)


def _detect_current_branch(project_root: Path | None) -> str | None:
    """Return the branch name the CWD lives in, or None."""
    branch_root = _current_branch_root(project_root)
    return branch_root.name if branch_root else None


def _resolve_git_dir(path: Path) -> Path | None:
    """If *path* is a ``.git`` file (worktree pointer), return the resolved gitdir."""
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text.startswith("gitdir:"):
                return Path(text.split(":", 1)[1].strip()).resolve()
    except OSError as exc:
        logger.warning("Failed to read .git file at %s: %s", path, exc)
    return None


def check_protected_dirs(resolved: Path) -> tuple[bool, str]:
    """The carve-out half of the fence: .git, .trinity, .aipass, .codex, .agents.

    Split out of :func:`check_carveouts` so stale mode can keep this half while
    crossing the sibling-branch half. Returns ``(blocked, reason)``.
    """
    parts = resolved.parts
    for i, part in enumerate(parts):
        if part in _CARVEOUT_DIRS:
            return True, f"Protected directory: path is inside {part}/"

        if part == ".git":
            git_path = Path(*parts[: i + 1]) if i > 0 else Path(part)
            real_gitdir = _resolve_git_dir(git_path)
            if real_gitdir and resolved.is_relative_to(real_gitdir):
                return True, "Protected: path resolves inside .git worktree gitdir"

    return False, ""


def check_carveouts(resolved: Path, project_root: Path | None) -> tuple[bool, str]:
    """Refuse deletion of protected paths even inside allowed roots.

    Returns ``(blocked, reason)``.  ``blocked=True`` means the path must
    NOT be deleted.
    """
    blocked, reason = check_protected_dirs(resolved)
    if blocked:
        return blocked, reason

    if project_root is not None:
        target_branch_root = _find_branch_root(resolved, project_root)
        if target_branch_root is not None:
            current_branch = _detect_current_branch(project_root)
            if current_branch is None or target_branch_root.name != current_branch:
                return True, f"Protected: path is inside sibling branch {target_branch_root.name}/"

    return check_contained_citizens(resolved, project_root)


def check_contained_citizens(resolved: Path, project_root: Path | None) -> tuple[bool, str]:
    """Refuse a project directory that CONTAINS a citizen other than the caller.

    The sibling fence walks UP from the target, so it only sees a citizen the
    target sits inside. A target ABOVE the branches — ``drone rm ..`` from a
    branch is ``src/aipass/``, ``../..`` is ``src/`` — has no ``.trinity``
    above it, passed every guard, and rmtree would have taken the fleet
    (DPLAN-0338 follow-up). This walks DOWN and stops at the first foreign
    citizen, which the refusal names.

    Scope, so nothing that worked before changes:
      - only directories under the project root; the system temp dir is not
        a place citizens live and keeps its old behaviour;
      - a target already inside a branch returns at once. Everything below it
        shares that branch's owner (outermost wins), the sibling fence has
        answered for it, and a template skeleton under @spawn stays @spawn's;
      - the caller's own branch is pruned whole, for the same reason;
      - a symlink is not a citizen: rmtree unlinks the link, never what it
        points at, and the walk does not follow one.

    A folder the walk cannot list refuses the delete: a guard that could not
    look must not report clear. Returns ``(blocked, reason)``.
    """
    if project_root is None or not resolved.is_relative_to(project_root) or not resolved.is_dir():
        return False, ""
    if _find_branch_root(resolved, project_root) is not None:
        return False, ""

    own = _current_branch_root(project_root)
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

    Returns ``(allowed, reason)``.  Refuses the root directories themselves.
    When multiple roots are nested (e.g. temp dir and a subdirectory of it),
    the path must not equal ANY root — checked upfront before containment.
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
    """Delete *paths* with containment checks.

    Returns a list of ``(original_path, success, message)`` tuples.
    Every path is checked independently; a refused path does not block others.
    """
    return _safe_delete_direct(paths)


def _standing_inside(resolved: Path, cwd: Path | None) -> str:
    """Name the caller's own position when that is what blocked the delete.

    Windows holds a process's current directory open without delete sharing, so
    removing a tree you are standing in fails with WinError 32 — and the fleet's
    normal spelling puts you there, because the target is an argument and nobody
    cds first: ``drone rm ..`` from a branch deletes the parent of your own cwd.
    POSIX permits that delete, so this only ever appends on the host that
    refused, and it says the one thing that gets the caller unstuck. Added to
    the message only; whose refusal it was does not change.
    """
    if cwd is None or not cwd.is_relative_to(resolved):
        return ""
    return f" — this process is standing in {cwd}; run drone rm from outside {resolved}"


def _safe_delete_direct(paths: list[str]) -> list[tuple[str, bool, str]]:
    """Delete paths directly (unsandboxed mode — current behavior)."""
    roots = get_allowed_roots()
    if not roots:
        return [(p, False, "No allowed roots found (no project registry, no temp dir)") for p in paths]

    project_root = _find_project_root()
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
            # A relative path names a place RELATIVE TO somewhere, and there is
            # no somewhere. Refused per path rather than for the whole call, so
            # `drone rm ./scratch /tmp/victim` still deletes what it can name.
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
            )
            continue

        # Measured here and not a line later: after rmtree there is nothing
        # left to ask how big it was.
        measurement = deletion_log.measure(absolute)

        try:
            # A link is removed as the link. Anything else is deleted at the
            # RESOLVED path, the one every guard above judged: `drone rm ..`
            # handed rmtree "spawn/..", which emptied the tree and then failed
            # its last rmdir, because spawn was gone by then. The ledger said
            # "failed" for a delete that had happened.
            if absolute.is_symlink():
                absolute.unlink()
            elif resolved.is_dir():
                shutil.rmtree(resolved)
            else:
                resolved.unlink()
            message = f"Deleted: {resolved}"
            results.append((path_str, True, message))
            logger.info("rm: deleted %s (resolved %s)", path_str, resolved)
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_DELETED,
                requested=path_str,
                resolved=resolved,
                reason=message,
                measurement=measurement,
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
            )

    return results


# ---------------------------------------------------------------------------
# Stale mode — drone rm --stale AGE [--dry-run] DIR [DIR...]  (DPLAN-0338)
# ---------------------------------------------------------------------------

MODE_STALE = "stale"
STALE_FLAG = "--stale"
DRY_RUN_FLAG = "--dry-run"

_STALE_FILE_SUFFIX = ".tmp"
_STALE_FOLDER_SUFFIX = "_json"

_AGE_UNITS = {"d": 86_400, "h": 3_600, "m": 60}
_AGE_FORMS = "10d (days), 36h (hours) or 90m (minutes)"
# [0-9], not \d: \d matches every Unicode digit and int() reads them all, so
# "٣d" would have parsed as three days.
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

    Any slot, because the plain lane reads every token as a path to delete:
    ``drone rm api_json --stale 10d`` left to it removes the whole folder, and
    ``--stale=10d`` left to it is a not-found beside a real delete of every
    DIR. So every token starting ``--stale`` comes here, where it is parsed or
    refused before anything is touched.
    """
    return any(token.startswith(STALE_FLAG) for token in tokens)


def parse_age(text: str) -> int:
    """Seconds in a stale-mode AGE: ``10d``, ``36h`` or ``90m``.

    Raises ValueError naming the three forms. Zero is refused as well: an age
    of zero matches a staged write that is in flight right now, and unlinking
    its temp fails that write's rename.
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

    ``--stale=AGE`` is read too. Raises ValueError — before any walk or delete —
    on a missing or malformed AGE, a repeated ``--stale``, no DIR, or any other
    token starting with ``-``: an unknown option is most likely a mistyped
    ``--dry-run``, and reading it as a DIR would turn a rehearsal into a sweep.
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

    A candidate is a regular file — never a symlink, never a directory — whose
    name ends ``.tmp``, whose PARENT folder's name ends ``_json``, and whose
    mtime is older than now minus the age. Nothing else is ever touched.

    Each DIR must resolve under the project root (the temp roots the plain lane
    also allows are not swept here) and outside the carve-outs. The walk never
    enters a carve-out directory and never follows a symlink.

    The sibling-branch fence is crossed here and only here, by design
    (DPLAN-0338, Patrick's go 2026-09-11): a stale staging temp is no citizen's
    work — the real json beside it is intact whatever happens to the temp — and
    one weekly job must sweep every branch's json folder in one call. The name,
    folder and age restriction is the fence instead.

    Every delete and every refusal is recorded with ``mode: stale`` and the
    age. A dry run deletes nothing, so it records nothing; its refusals still
    count and still print.
    """
    report = StaleReport()
    json_handler.log_operation(
        "rm_stale",
        {"dirs": list(request.dirs), "age": request.age, "dry_run": request.dry_run},
    )
    project_root = _find_project_root()
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

    *visited* is shared across the DIRs of one run, so overlapping DIRs walk a
    folder once and never match — or try to delete — the same file twice.
    """
    found: list[tuple[Path, float, int]] = []

    def _unreadable(exc: OSError) -> None:
        # os.walk's default skips what it cannot list, in silence. A sweep that
        # did not look somewhere must not report clean.
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
        dirnames[:] = [name for name in dirnames if name not in _CARVEOUT_DIRS]
        if not here.name.endswith(_STALE_FOLDER_SUFFIX):
            continue
        for name in filenames:
            if not name.endswith(_STALE_FILE_SUFFIX):
                continue
            path = here / name
            try:
                info = path.lstat()
            except FileNotFoundError:
                # Gone between the listing and the look: nothing left to sweep.
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
