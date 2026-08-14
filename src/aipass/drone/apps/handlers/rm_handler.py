# =================== AIPass ====================
# Name: rm_handler.py
# Description: Contained safe-delete handler
# Version: 1.1.0
# Created: 2026-06-02
# Modified: 2026-06-02
# =============================================

"""Contained safe-delete handler.

Deletes paths using shutil.rmtree (directories) or Path.unlink (files),
constrained to project root and system temp directories. Provider-agnostic
alternative to shell ``rm``.

Matches Codex sandbox boundaries: writable = {project, /tmp, $TMPDIR}.
Hard carve-outs protect .git, .trinity, .aipass, .codex, .agents, and
sibling branch worktrees even inside allowed roots.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers import deletion_log
from aipass.drone.apps.handlers.json import json_handler

_CARVEOUT_DIRS = frozenset((".git", ".trinity", ".aipass", ".codex", ".agents"))


def _find_project_root() -> Path | None:
    """Walk up from CWD to find *_REGISTRY.json; return its parent as project root."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if list(parent.glob("*_REGISTRY.json")):
            return parent.resolve()
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        home = Path(aipass_home)
        if home.is_dir() and list(home.glob("*_REGISTRY.json")):
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


def _detect_current_branch(project_root: Path | None) -> str | None:
    """Return the branch name the CWD lives in, or None."""
    if project_root is None:
        return None
    branch_root = _find_branch_root(Path.cwd().resolve(), project_root)
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


def check_carveouts(resolved: Path, project_root: Path | None) -> tuple[bool, str]:
    """Refuse deletion of protected paths even inside allowed roots.

    Returns ``(blocked, reason)``.  ``blocked=True`` means the path must
    NOT be deleted.
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

    if project_root is not None:
        target_branch_root = _find_branch_root(resolved, project_root)
        if target_branch_root is not None:
            current_branch = _detect_current_branch(project_root)
            if current_branch is None or target_branch_root.name != current_branch:
                return True, f"Protected: path is inside sibling branch {target_branch_root.name}/"

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


def _safe_delete_direct(paths: list[str]) -> list[tuple[str, bool, str]]:
    """Delete paths directly (unsandboxed mode — current behavior)."""
    roots = get_allowed_roots()
    if not roots:
        return [(p, False, "No allowed roots found (no project registry, no temp dir)") for p in paths]

    project_root = _find_project_root()
    json_handler.log_operation("rm", {"paths": paths, "roots": [str(r) for r in roots]})

    results: list[tuple[str, bool, str]] = []
    for path_str in paths:
        original = Path(path_str)
        absolute = original if original.is_absolute() else (Path.cwd() / original)

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
            if absolute.is_symlink():
                absolute.unlink()
            elif absolute.is_dir():
                shutil.rmtree(absolute)
            else:
                absolute.unlink()
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
            results.append((path_str, False, f"Delete failed: {exc}"))
            logger.error("rm: delete failed for %s: %s", path_str, exc)
            deletion_log.record_deletion(
                lane=deletion_log.LANE_RM,
                outcome=deletion_log.OUTCOME_FAILED,
                requested=path_str,
                resolved=resolved,
                reason=f"Delete failed: {exc}",
                measurement=measurement,
            )

    return results
