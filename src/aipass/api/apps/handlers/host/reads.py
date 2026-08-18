# =================== AIPass ====================
# Name: reads.py
# Description: Host API Read Handler — file and directory reads behind the name fence
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Read Handler

File and diff reads for the phone's read lane (FPLAN-0411 Phase 2).

THE NAME FENCE — @baud's doctrine, adopted because it beats what I had
------------------------------------------------------------------------
My first design took a path parameter and hardened it with traversal
containment. @baud's rule is better: the client sends NAMES, never paths, and
the server resolves them. That does not mitigate the traversal risk class, it
DELETES it — with no path parameter there is nothing for a remote caller to
point at, and "jailed" stops being a string comparison someone has to get right
forever.

Containment is still implemented underneath, because a "name" can still carry a
separator or a `..`, and because resolve() following a symlink out of the tree
would otherwise go unnoticed. The fence removes the class; the check catches the
liar.

Branch names resolve through the citizen registry — the system's own catalog of
who exists and where. This handler reads that catalog; it never decides what a
branch is. Same D0 line as everywhere else in this package.

Caps: 512KB on both files and diffs, matching BAUD's read fence. A cap that is
hit is REPORTED, never a silent truncation.

Functions:
    resolve_branch_root() - Registry lookup, branch name to absolute path
    read_file()           - Read one file under a branch, fenced and capped
    list_dir()            - One level of one directory, fenced and capped
    seated_project()      - The project this server is seated in
    repo_root()           - The seat's repository root

The repository-shaped reads used to live here too, and this file crossed the
1500-line cap carrying them. They now sit in git_reads.py (the patch, the change
list, the log, one commit) and remotes.py (where a repository points), both of
which lean on the resolution and the fence below. The dependency runs one way.
"""

from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# @drone's public package surface — its own branch resolution, not our reading of
# their registry. Same door shape as `from aipass.prax import logger`.
import aipass.drone as drone

MAX_READ_BYTES = 512 * 1024

# One level of one branch, phone-sized. A cap hit is flagged, not refused — an
# over-full directory should still browse, it just says what it dropped.
MAX_DIR_ENTRIES = 400

# Machine residue, not content — the same six the desktop's tree never
# descends into (NOISE_DIRS in @baud's lib.rs). Kept in step by name.
NOISE_DIRS = frozenset({".git", "node_modules", "target", "__pycache__", ".venv", "dist"})

# GRAIN — the vocabulary of the whole read surface, which is why it stays on
# this side of the split: every answer names its own scope, and both halves say
# it in the same two words.
#
# Two grains, both honest. The card asks about one branch; the app asks about
# the repository the branch lives in (Patrick's ruling, DPLAN-0303 08-17). A
# lane that served one while a caller believed the other would be wrong in the
# most expensive way — silently.
GRAIN_BRANCH = "branch"
GRAIN_REPO = "repo"
GRAINS = (GRAIN_BRANCH, GRAIN_REPO)


class ReadRefused(Exception):
    """A read was refused. Carries the reason the caller is allowed to know."""


class ReadUnavailable(Exception):
    """A read could not be completed for a reason that is not the caller's fault."""


# ==============================================
# RESOLUTION
# ==============================================


def _registry_path() -> Path:
    """
    Locate the citizen registry through drone's public surface.

    Args:
        None.

    Returns:
        Path to the registry file.
    """
    return Path(drone.get_registry_path())


def repo_root() -> Path:
    """
    The repository root this server is seated in.

    Returns:
        Absolute path to the repo root.
    """
    return _registry_path().parent


def seated_project() -> str:
    """
    The project name this server is seated in.

    THE SEAT IS NO LONGER A FENCE ON THIS LANE — it is a default and a fast
    path. Patrick's ruling, 2026-08-16: "I should be able to open another
    project via the project tab drop down, and view other agent project files,
    open any passport and view watch read files. no restriction." Browsing is
    free; the terminal binds to the seat; attach is the only takeover. So reads
    serve any project @baud's census knows, exactly as /v1/fleet already did,
    and this name now answers "which project do I mean when nobody says" rather
    than "which project am I allowed to answer about".

    Returns:
        The seated project's directory name.
    """
    return repo_root().name


def _is_seated(project: str) -> bool:
    """
    Whether a caller-supplied project names the seat.

    Case-insensitive, and that asymmetry is deliberate: the wire says AIPASS,
    the directory says AIPass, and a case-sensitive check here would refuse the
    seat's own real name. Foreign projects travel VERBATIM to @baud instead, so
    their census keeps the one ruling on how a project name is matched.

    Args:
        project: Project name from the request, or empty for the default.

    Returns:
        True when this server can answer from its own registry.
    """
    return not project.strip() or project.strip().lower() == seated_project().lower()


def _external_branch_root(project: str, branch: str) -> Path:
    """
    Resolve a branch inside ANOTHER project, through @baud's own census.

    This server never composes a filesystem path for a project it is not seated
    in. The row comes from BAUD's discovery — the same engine the desktop trusts
    and the same door the attach lane already uses for external rooms — so there
    is one implementation of "where does this project's branch live".

    Args:
        project: Census name, travelling verbatim.
        branch: Branch name, with or without the leading '@'.

    Returns:
        Absolute path to the branch directory.

    Raises:
        ReadRefused: The project has no branch by that name.
        ReadUnavailable: The census could not be produced, or names no such
            project — @baud's sentence, carried unchanged.
    """
    # Imported HERE, not at module scope, because fleet.py imports repo_root()
    # from this file: a module-level import would be a cycle and would fail at
    # startup. The real fix is that repo_root() is a location primitive and
    # belongs below both of us rather than in the read lane — reported rather
    # than done mid-train, since moving a name four files import is not a
    # change to make on the night the phone is live.
    from aipass.api.apps.handlers.host import fleet as host_fleet

    try:
        row = host_fleet.resolve_branch(project, branch)
    except host_fleet.FleetUnavailable as e:
        # An unknown project lands here in @baud's words, and so does a gated
        # or broken census. Both are 503: neither is the caller mistyping a
        # branch, and neither is this server's to phrase.
        logger.info("[host_api] census could not resolve %r in %r: %s", branch, project, e)
        raise ReadUnavailable(str(e)) from e

    if row is None:
        # Unknown BRANCH in a known project — the caller's mistake, and phrased
        # exactly as the attach lane phrases the same one.
        raise ReadRefused(f"Project {project!r} has no branch named {branch!r}")

    root = Path(str(row.get("path", ""))).resolve()
    if not root.is_dir():
        raise ReadUnavailable(f"{project} lists {branch!r} at a path that does not exist: {root}")

    return root


def resolve_branch_root(branch: str, project: str = "") -> Path:
    """
    Resolve a branch name to its absolute path.

    Two doors, and which one opens depends only on whether the caller named a
    project other than the seat. The seated door is drone's citizen registry —
    local, no subprocess, and the path every read took before tonight. A foreign
    project goes through @baud's census instead.

    Args:
        branch: Branch name or email, with or without the leading '@'.
        project: Optional project name. Empty or the seat's own name uses the
            local registry; anything else resolves through @baud.

    Returns:
        Absolute path to the branch directory.

    Raises:
        ReadRefused: The branch is not a registered citizen, or the named
            project has no branch by that name.
        ReadUnavailable: The registry or the census could not be read.
    """
    if not branch or not branch.strip():
        raise ReadRefused("A branch name is required")

    if not _is_seated(project):
        return _external_branch_root(project, branch)

    wanted = branch.strip().lstrip("@")

    try:
        info = drone.get_branch_info(wanted)
    except drone.BranchNotFoundError as e:
        # The caller's mistake: they named something that is not a citizen. They
        # learn that and nothing more — never a filesystem path.
        logger.info("[host_api] unknown branch requested: %r", branch)
        raise ReadRefused(f"Unknown branch: {branch!r}") from e
    except drone.RegistryError as e:
        # OUR problem, not theirs. Kept distinct on purpose: collapsing a broken
        # registry into "unknown branch" would send an operator hunting for a
        # typo while the real fault is a corrupt catalog.
        logger.error("[host_api] citizen registry could not be read: %s", e)
        raise ReadUnavailable(f"Citizen registry could not be read: {e}") from e

    root = Path(str(info.get("path", ""))).resolve()
    if not root.is_dir():
        raise ReadUnavailable(f"Registry lists {branch!r} at a path that does not exist: {root}")

    return root


# ==============================================
# READS
# ==============================================


def read_file(branch: str, file: str, project: str = "") -> Dict[str, Any]:
    """
    Read one file under a branch.

    Args:
        branch: Branch name — resolved through the registry, never a path.
        file: Path RELATIVE to the branch root, e.g. "apps/api.py".
        project: Optional project name. Empty means the seat; any project
            @baud's census knows is served.

    Returns:
        Dict with branch, file, bytes, truncated (always False — a cap hit is an
        error here, not a quiet trim) and content.

    Raises:
        ReadRefused: Fence violation, unknown branch, missing file, over cap, or
            a file that is not UTF-8 text.
        ReadUnavailable: Registry or filesystem failure.
    """
    root = resolve_branch_root(branch, project)
    target = _fence(root, file)

    if not target.is_file():
        raise ReadRefused(f"Not a file: {file!r}")

    size = target.stat().st_size
    if size > MAX_READ_BYTES:
        # Named, not truncated. A silent trim reads as "this is the whole file".
        raise ReadRefused(f"File is {size} bytes, over the {MAX_READ_BYTES} byte read cap")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ReadRefused(f"Not UTF-8 text: {file!r}") from e
    except OSError as e:
        logger.error("[host_api] file read failed for %s: %s", target, e)
        raise ReadUnavailable(f"File could not be read: {e}") from e

    json_handler.log_operation("host_api_file_read", {"branch": branch, "file": file, "bytes": size})

    return {
        "branch": branch,
        "file": file,
        "bytes": size,
        "truncated": False,
        "content": content,
    }


def list_dir(branch: str, dir: str = "", project: str = "") -> Dict[str, Any]:
    """
    List one directory level under a branch — the phone's file browser.

    Mirrors the desktop's `list_dir`: dirs first, then files, both
    alphabetical, noise directories filtered at the source. One level only;
    the caller descends by asking again.

    Args:
        branch: Branch name — resolved through the registry, never a path.
        dir: Directory RELATIVE to the branch root, empty for the root itself.
        project: Optional project name. Empty means the seat; any project
            @baud's census knows is served.

    Returns:
        Dict with branch, dir, entries (name, path relative to the branch
        root, is_dir) and truncated — True when the level was over the cap
        and the tail was dropped.

    Raises:
        ReadRefused: Fence violation, unknown branch, or not a directory.
        ReadUnavailable: Registry or filesystem failure.
    """
    root = resolve_branch_root(branch, project)
    # The fence requires a name; the branch root itself is the one level the
    # caller may name with nothing.
    target = _fence(root, dir) if dir.strip() else root

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
                "path": str(child.relative_to(root)),
                "is_dir": is_child_dir,
            }
        )

    entries.sort(key=lambda entry: (not entry["is_dir"], entry["name"].lower()))
    truncated = len(entries) > MAX_DIR_ENTRIES
    if truncated:
        entries = entries[:MAX_DIR_ENTRIES]

    json_handler.log_operation(
        "host_api_dir_list",
        {"branch": branch, "dir": dir or ".", "entries": len(entries), "truncated": truncated},
    )

    return {
        "branch": branch,
        "dir": dir,
        "entries": entries,
        "truncated": truncated,
    }


# ==============================================
# THE FENCE
# ==============================================


def repository_of(root: Path) -> Optional[Path]:
    """
    The repository a directory actually sits in, found the way the tool does.

    Public, and on this side of the split, because BOTH halves of the read
    surface ask it: the change list strips row paths against the repository
    that owns them, and the remote lane looks for that repository's own
    configuration file. It was private while one module held everything; a
    function three modules depend on is not private.

    Args:
        root: A resolved directory — usually a branch root.

    Returns:
        The nearest ancestor carrying a '.git' marker, or None when there is
        none above this directory at all.

    Note:
        The marker is checked with exists(), not is_dir(): a worktree or a
        submodule carries it as a FILE, and reading those as "not a repository"
        would silently un-strip every row inside them.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _fence(root: Path, file: str) -> Path:
    """
    Turn a caller-supplied relative name into a verified path under *root*.

    Three gates, deliberately overlapping:
      1. Reject absolute names and drive-letter shapes outright.
      2. Reject any '..' component before touching the filesystem.
      3. Resolve, then verify the result still sits under root — this is what
         catches a symlink pointing out of the tree, which (1) and (2) cannot.

    Args:
        root: Absolute, resolved branch root.
        file: Caller-supplied relative name.

    Returns:
        The verified absolute path.

    Raises:
        ReadRefused: Any gate fails.
    """
    if not file or not file.strip():
        raise ReadRefused("A file name is required")

    candidate = file.strip()

    if candidate.startswith(("/", "\\")) or (len(candidate) > 1 and candidate[1] == ":"):
        raise ReadRefused("File must be relative to the branch, not an absolute path")

    parts = Path(candidate).parts
    if ".." in parts:
        raise ReadRefused("File name may not contain '..'")

    resolved = (root / candidate).resolve()

    # The last line of defence: a symlink inside the branch can still point out
    # of it, and only a post-resolution check sees that.
    if resolved != root and root not in resolved.parents:
        logger.warning("[host_api] fence blocked a read outside %s: %r", root, file)
        raise ReadRefused("File resolves outside the branch")

    if not resolved.exists():
        raise ReadRefused(f"No such file: {file!r}")

    return resolved
