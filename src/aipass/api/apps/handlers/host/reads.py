# =================== AIPass ====================
# Name: reads.py
# Description: Host API Read Handler — file and diff reads behind the name fence
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
    read_diff()           - Diff for a branch via drone's git read lane
    seated_project()      - The project this server is seated in
"""

import subprocess
from pathlib import Path
from typing import Any, Dict

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# @drone's public package surface — its own branch resolution, not our reading of
# their registry. Same door shape as `from aipass.prax import logger`.
import aipass.drone as drone

MAX_READ_BYTES = 512 * 1024

# Diffs are generated, not stored, so they get the same ceiling by policy.
MAX_DIFF_BYTES = 512 * 1024

DIFF_TIMEOUT_SECONDS = 30


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
    The project name this server serves.

    Phase 2 serves exactly one project — the one it is seated in. A `project`
    parameter that names anything else is refused rather than silently ignored,
    so a multi-project client learns the truth instead of reading the wrong tree.

    Returns:
        The seated project's directory name.
    """
    return repo_root().name


def resolve_branch_root(branch: str) -> Path:
    """
    Resolve a branch name to its absolute path via the citizen registry.

    Args:
        branch: Branch name or email, with or without the leading '@'.

    Returns:
        Absolute path to the branch directory.

    Raises:
        ReadRefused: The branch is not a registered citizen.
        ReadUnavailable: The registry could not be read.
    """
    if not branch or not branch.strip():
        raise ReadRefused("A branch name is required")

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


def _check_project(project: str) -> None:
    """
    Verify a caller-supplied project matches the seated one.

    Args:
        project: Project name from the request, or empty to accept the default.

    Raises:
        ReadRefused: The project names something this server does not serve.
    """
    if not project:
        return

    if project.strip().lower() != seated_project().lower():
        raise ReadRefused(f"This server is seated in {seated_project()!r} and does not serve project {project!r}")


# ==============================================
# READS
# ==============================================


def read_file(branch: str, file: str, project: str = "") -> Dict[str, Any]:
    """
    Read one file under a branch.

    Args:
        branch: Branch name — resolved through the registry, never a path.
        file: Path RELATIVE to the branch root, e.g. "apps/api.py".
        project: Optional project name; must match the seated project.

    Returns:
        Dict with branch, file, bytes, truncated (always False — a cap hit is an
        error here, not a quiet trim) and content.

    Raises:
        ReadRefused: Fence violation, unknown branch, missing file, over cap, or
            a file that is not UTF-8 text.
        ReadUnavailable: Registry or filesystem failure.
    """
    _check_project(project)
    root = resolve_branch_root(branch)
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


def read_diff(branch: str, staged: bool = False, project: str = "") -> Dict[str, Any]:
    """
    Read a branch's git diff.

    Git is drone-only in this system — house rule, and not one this server gets
    to bend because it happens to be a server. This shells `drone @git diff`
    with the branch as its working directory, exactly as an operator would.

    Args:
        branch: Branch name, resolved through the registry.
        staged: Whether to ask for the staged diff.
        project: Optional project name; must match the seated project.

    Returns:
        Dict with branch, staged, bytes, truncated and diff text.

    Raises:
        ReadRefused: Unknown branch or a project mismatch.
        ReadUnavailable: drone could not be run, or timed out.
    """
    _check_project(project)
    root = resolve_branch_root(branch)

    command = ["drone", "@git", "diff"] + (["--staged"] if staged else [])

    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] drone not found for the diff lane: %s", e)
        raise ReadUnavailable("drone is not available on PATH — the diff lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] diff timed out for %s after %ss", branch, DIFF_TIMEOUT_SECONDS)
        raise ReadUnavailable(f"Diff timed out after {DIFF_TIMEOUT_SECONDS}s") from e

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        logger.warning("[host_api] diff returned %s for %s: %s", result.returncode, branch, stderr)
        raise ReadUnavailable(f"Diff failed: {stderr or 'no detail'}")

    diff = result.stdout or ""
    raw_bytes = len(diff.encode("utf-8"))
    truncated = raw_bytes > MAX_DIFF_BYTES

    if truncated:
        # A diff is generated, so capping it is reasonable — but the cap is
        # REPORTED. No silent truncation reading as a complete diff.
        diff = diff.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        logger.info("[host_api] diff for %s truncated at %d bytes", branch, MAX_DIFF_BYTES)

    json_handler.log_operation(
        "host_api_diff_read",
        {"branch": branch, "staged": staged, "bytes": raw_bytes, "truncated": truncated},
    )

    return {
        "branch": branch,
        "staged": staged,
        "bytes": raw_bytes,
        "truncated": truncated,
        "diff": diff,
    }


# ==============================================
# THE FENCE
# ==============================================


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
