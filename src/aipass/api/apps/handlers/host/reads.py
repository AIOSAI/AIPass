# =================== AIPass ====================
# Name: reads.py
# Description: Host API Read Handler — file and directory reads behind the name fence
# Version: 1.2.1
# Created: 2026-08-14
# Modified: 2026-10-24
# =============================================

"""
Host API Read Handler

Reference: docs/host_api.md
No deny-list, by ruling: a read-scope token can read ~/.ssh.
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

import aipass.drone as drone

MAX_READ_BYTES = 512 * 1024

# A cap hit is flagged, not refused: an over-full directory still browses, a page at a time by offset.
MAX_DIR_ENTRIES = 400

# Kept in step by name with NOISE_DIRS in @baud's lib.rs.
NOISE_DIRS = frozenset({".git", "node_modules", "target", "__pycache__", ".venv", "dist"})

GRAIN_BRANCH = "branch"
GRAIN_REPO = "repo"
GRAINS = (GRAIN_BRANCH, GRAIN_REPO)

ROOT_BRANCH = "branch"
ROOT_HOME = "home"
ROOT_PROJECT = "project"
ROOT_AIPASS = "aipass"
ROOT_KINDS = (ROOT_BRANCH, ROOT_HOME, ROOT_PROJECT, ROOT_AIPASS)

_NAMELESS_KINDS = (ROOT_HOME, ROOT_AIPASS)


class ReadRefused(Exception):
    """A read was refused. Carries the reason the caller is allowed to know."""


class ReadUnavailable(Exception):
    """A read could not be completed for a reason that is not the caller's fault."""


def _registry_path() -> Path:
    """Locate the citizen registry through drone's public surface."""
    return Path(drone.get_registry_path())


def repo_root() -> Path:
    """The repository root this server is seated in."""
    return _registry_path().parent


def home_root() -> Path:
    """The operator's home directory — the root the owner named first."""
    return Path.home().resolve()


def seated_project() -> str:
    """The project name this server is seated in."""
    return repo_root().name


def _is_seated(project: str) -> bool:
    """Whether a caller-supplied project names the seat."""
    # Case-insensitive: the wire says AIPASS, the directory AIPass.
    return not project.strip() or project.strip().lower() == seated_project().lower()


def _external_branch_root(project: str, branch: str) -> Path:
    """Resolve a branch inside ANOTHER project, through @baud's own census."""
    # Function-scope import: fleet.py imports repo_root() from this file, so a
    # module-level import is a startup cycle.
    from aipass.api.apps.handlers.host import fleet as host_fleet

    try:
        row = host_fleet.resolve_branch(project, branch)
    except host_fleet.FleetUnavailable as e:
        # Unknown project and broken census both land here: 503, in @baud's words.
        logger.info("[host_api] census could not resolve %r in %r: %s", branch, project, e)
        raise ReadUnavailable(str(e)) from e

    if row is None:
        raise ReadRefused(f"Project {project!r} has no branch named {branch!r}")

    root = Path(str(row.get("path", ""))).resolve()
    if not root.is_dir():
        raise ReadUnavailable(f"{project} lists {branch!r} at a path that does not exist: {root}")

    return root


def resolve_branch_root(branch: str, project: str = "") -> Path:
    """Resolve a branch name to its absolute path."""
    if not branch or not branch.strip():
        raise ReadRefused("A branch name is required")

    if not _is_seated(project):
        return _external_branch_root(project, branch)

    wanted = branch.strip().lstrip("@")

    try:
        info = drone.get_branch_info(wanted)
    except drone.BranchNotFoundError as e:
        logger.info("[host_api] unknown branch requested: %r", branch)
        raise ReadRefused(f"Unknown branch: {branch!r}") from e
    except drone.RegistryError as e:
        # Kept distinct from "unknown branch": a corrupt catalog is not a typo.
        logger.error("[host_api] citizen registry could not be read: %s", e)
        raise ReadUnavailable(f"Citizen registry could not be read: {e}") from e

    listed = str(info.get("path", "")).strip()
    if not listed:
        # Path("") resolves to the CWD, a real directory that would read as the branch.
        raise ReadUnavailable(f"Registry lists {branch!r} without a path")

    root = Path(listed).resolve()
    if not root.is_dir():
        raise ReadUnavailable(f"Registry lists {branch!r} at a path that does not exist: {root}")

    return root


def _project_root(name: str) -> Path:
    """Resolve a project name to its root, through @baud's census."""
    wanted = name.strip()
    if not wanted:
        raise ReadRefused(f"A project name is required for the {ROOT_PROJECT!r} root")

    from aipass.api.apps.handlers.host import fleet as host_fleet

    try:
        census = host_fleet.list_projects()
    except host_fleet.FleetUnavailable as e:
        logger.info("[host_api] census could not be produced for root %r: %s", wanted, e)
        raise ReadUnavailable(str(e)) from e

    for row in census.get("projects") or []:
        # Exact: the name comes from the /v1/roots roster published from this census.
        if str(row.get("name", "")) != wanted:
            continue

        listed = str(row.get("root", "")).strip()
        if not listed:
            raise ReadUnavailable(f"The census lists {wanted!r} without a path")

        return Path(listed).resolve()

    raise ReadRefused(f"No project named {wanted!r} in the roster — the names come from /v1/roots")


def resolve_root(kind: str, name: str = "", project: str = "") -> Path:
    """
    Resolve one of the fence's four kinds of word to an absolute floor.

    A parameter that cannot mean anything is refused, never dropped. No default
    kind: "absent means branch" is the read lane's rule, not the resolver's.
    """
    if kind not in ROOT_KINDS:
        raise ReadRefused(f"Unknown root kind: {kind!r}. The fence answers {', '.join(ROOT_KINDS)}")

    if kind == ROOT_BRANCH:
        return resolve_branch_root(name, project)

    if project.strip():
        raise ReadRefused(f"The {kind!r} root does not live inside a project — send no project")

    if kind in _NAMELESS_KINDS and name.strip() and name.strip() != kind:
        # A nameless kind may name itself: @baud's browser sends a component for every root.
        raise ReadRefused(f"The {kind!r} root names nothing — send no name, or the kind itself; received {name!r}")

    if kind == ROOT_HOME:
        try:
            root = home_root()
        except RuntimeError as e:
            logger.error("[host_api] the home directory could not be determined: %s", e)
            raise ReadUnavailable(f"The home directory could not be determined: {e}") from e
    elif kind == ROOT_AIPASS:
        root = repo_root().resolve()
    else:
        root = _project_root(name)

    if not root.is_dir():
        raise ReadUnavailable(f"The {kind!r} root is not a directory: {root}")

    return root


def list_roots() -> Dict[str, Any]:
    """Every place the file lane may stand — the roster the phone's picker renders."""
    from aipass.api.apps.handlers.host import fleet as host_fleet

    aipass = repo_root().resolve()

    roots: list = [
        {"kind": ROOT_HOME, "name": "", "label": "home"},
        {"kind": ROOT_AIPASS, "name": "", "label": aipass.name},
    ]

    try:
        census = host_fleet.list_projects()
    except host_fleet.FleetUnavailable as e:
        # Whole roster refused: @baud's RootsScreen reads only `roots`, so a partial one prints "no projects".
        logger.info("[host_api] roots roster refused — no census: %s", e)
        raise ReadUnavailable(str(e)) from e

    dropped = []
    for row in census.get("projects") or []:
        name = str(row.get("name", "")).strip()
        listed = str(row.get("root", "")).strip()

        if not name or not listed:
            dropped.append(row)
            continue

        root = Path(listed).resolve()
        # One row per floor: the anchor project is the aipass root, and both selectors still resolve.
        if root == aipass:
            continue

        roots.append({"kind": ROOT_PROJECT, "name": name, "label": root.name or name})

    if dropped:
        logger.warning("[host_api] roots roster dropped %s census row(s) with no name or path", len(dropped))

    json_handler.log_operation("host_api_roots_roster", {"roots": len(roots), "dropped": len(dropped)})

    return {"roots": roots}


def published_root_of(directory: Path) -> Optional[Dict[str, Any]]:
    """
    The /v1/roots root a directory IS, by resolved-path equality, never a prefix.

    aipass first, as in list_roots: an anchor census row that is the seat publishes as aipass.
    None when it is neither. A census that cannot answer raises: None would claim "neither".
    """
    resolved = directory.resolve()
    if resolved == repo_root().resolve():
        return {"kind": ROOT_AIPASS, "name": None}

    from aipass.api.apps.handlers.host import fleet as host_fleet

    try:
        census = host_fleet.list_projects()
    except host_fleet.FleetUnavailable as e:
        logger.warning("[host_api] no census to name the root of %s: %s", resolved, e)
        raise ReadUnavailable(str(e)) from e

    for row in census.get("projects") or []:
        name = str(row.get("name", "")).strip()
        listed = str(row.get("root", "")).strip()
        if name and listed and Path(listed).resolve() == resolved:
            return {"kind": ROOT_PROJECT, "name": name}

    return None


def read_file(branch: str, file: str, project: str = "", root: str = "") -> Dict[str, Any]:
    """Read one file under a named root."""
    floor = resolve_root(root or ROOT_BRANCH, branch, project)
    target = _fence(floor, file)

    if not target.is_file():
        raise ReadRefused(f"Not a file: {file!r}")

    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        # Refused, not truncated: a silent trim reads as "this is the whole file".
        raise ReadRefused(f"File is {size} bytes, over the {MAX_READ_BYTES} byte read cap")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ReadRefused(f"Not UTF-8 text: {file!r}") from e
    except OSError as e:
        logger.error("[host_api] file read failed for %s: %s", target, e)
        raise ReadUnavailable(f"File could not be read: {e}") from e

    # The audit names the root so a home read never looks like a branch read.
    audit: Dict[str, Any] = {"branch": branch, "file": file, "bytes": size}
    if root:
        audit["root"] = root
    json_handler.log_operation("host_api_file_read", audit)

    answer = {
        "branch": branch,
        "file": file,
        "bytes": size,
        "truncated": False,
        "content": content,
        "floor": str(floor),
    }
    if root:
        answer["root"] = root

    return answer


def _dir_offset(raw: Any) -> int:
    """The page start: a whole number, never negative. A str is what the route passes."""
    if isinstance(raw, bool):
        raise ReadRefused("offset must be a whole number")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ReadRefused("offset must be a whole number") from None
    if value < 0:
        raise ReadRefused("offset must not be negative")
    return value


def list_dir(branch: str = "", dir: str = "", project: str = "", root: str = "", offset: Any = 0) -> Dict[str, Any]:
    """List one directory level under a named root — the phone's file browser, a page at a time."""
    start = _dir_offset(offset)
    floor = resolve_root(root or ROOT_BRANCH, branch, project)
    target = _fence(floor, dir) if dir.strip() else floor

    if not target.is_dir():
        raise ReadRefused(f"Not a directory: {dir!r}")

    try:
        children = list(target.iterdir())
    except OSError as e:
        logger.error("[host_api] directory listing failed for %s: %s", target, e)
        raise ReadUnavailable(f"Directory could not be listed: {e}") from e

    entries = []
    for child in children:
        is_child_dir = child.is_dir()
        if is_child_dir and child.name in NOISE_DIRS:
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child.relative_to(floor)),
                "is_dir": is_child_dir,
            }
        )

    entries.sort(key=lambda entry: (not entry["is_dir"], entry["name"].lower()))
    total = len(entries)
    entries = entries[start : start + MAX_DIR_ENTRIES]
    truncated = start + len(entries) < total

    audit: Dict[str, Any] = {
        "branch": branch,
        "dir": dir or ".",
        "entries": len(entries),
        "truncated": truncated,
        "offset": start,
        "total": total,
    }
    if root:
        audit["root"] = root
    json_handler.log_operation("host_api_dir_list", audit)

    answer = {
        "branch": branch,
        "dir": dir,
        "entries": entries,
        "truncated": truncated,
        "offset": start,
        "total": total,
        # The root's path, not the listed directory's: entry paths are already
        # root-relative, so walking with `dir` would double it on the face's join.
        "floor": str(floor),
    }
    if root:
        answer["root"] = root

    return answer


def repository_of(root: Path) -> Optional[Path]:
    """The repository a directory actually sits in, found the way the tool does."""
    # exists(), not is_dir(): a worktree or submodule carries '.git' as a file.
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _fence(root: Path, file: str) -> Path:
    """Turn a caller-supplied relative name into a verified path under *root*."""
    if not file or not file.strip():
        raise ReadRefused("A file name is required")

    candidate = file.strip()

    # Before realpath, which raises ValueError on a NUL.
    if "\x00" in candidate:
        raise ReadRefused("File name may not contain a NUL byte")

    if candidate.startswith(("/", "\\")) or (len(candidate) > 1 and candidate[1] == ":"):
        raise ReadRefused("File must be relative to the root, not an absolute path")

    parts = Path(candidate).parts
    if ".." in parts:
        raise ReadRefused("File name may not contain '..'")

    base = os.path.realpath(root)
    real = os.path.realpath(os.path.join(base, candidate))
    if real == base:
        return root

    # Only a post-resolution check catches a symlink out; realpath plus startswith is the guard CodeQL reads.
    if not real.startswith(base + os.sep):
        logger.warning("[host_api] fence blocked a read outside %s: %r", root, file)
        raise ReadRefused("File resolves outside the root")

    resolved = Path(real)
    if not resolved.exists():
        raise ReadRefused(f"No such file: {file!r}")

    return resolved
