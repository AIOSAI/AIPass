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
    read_git_changes()    - A branch's changed-file list, @baud's card contract
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

# One level of one branch, phone-sized. A cap hit is flagged, not refused — an
# over-full directory should still browse, it just says what it dropped.
MAX_DIR_ENTRIES = 400

# Machine residue, not content — the same six the desktop's tree never
# descends into (NOISE_DIRS in @baud's lib.rs). Kept in step by name.
NOISE_DIRS = frozenset({".git", "node_modules", "target", "__pycache__", ".venv", "dist"})

# Diffs are generated, not stored, so they get the same ceiling by policy.
MAX_DIFF_BYTES = 512 * 1024

DIFF_TIMEOUT_SECONDS = 30

# Porcelain's two status columns, as drone re-renders them: two spaces, the
# code right-aligned in two, one space, then the path. Keyed on that structure
# and on git's own codes — never on the prose drone frames the list with.
STATUS_INDENT = "  "
STATUS_CODE_SLICE = slice(2, 4)
STATUS_PATH_FROM = 5

# git's own words for "not in the repository" and "ignored". Everything else in
# a porcelain listing is a TRACKED path that differs from HEAD — which is
# exactly what `git diff HEAD --name-only` answers, and therefore exactly what
# @baud's desktop card counts.
UNTRACKED_CODE = "??"
IGNORED_CODE = "!!"

# Porcelain writes a rename as 'old -> new' on one line.
RENAME_ARROW = " -> "


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


def read_diff(branch: str, staged: bool = False, project: str = "") -> Dict[str, Any]:
    """
    Read a branch's git diff.

    Git is drone-only in this system — house rule, and not one this server gets
    to bend because it happens to be a server. This shells `drone @git diff`
    with the branch as its working directory, exactly as an operator would.

    Args:
        branch: Branch name, resolved through the registry.
        staged: Whether to ask for the staged diff.
        project: Optional project name. Empty means the seat; any project
            @baud's census knows is served.

    Returns:
        Dict with branch, staged, bytes, truncated and diff text.

    Raises:
        ReadRefused: Unknown branch, or a project with no such branch.
        ReadUnavailable: drone could not be run, or timed out.
    """
    root = resolve_branch_root(branch, project)

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


def read_git_changes(branch: str, project: str = "") -> Dict[str, Any]:
    """
    A branch's uncommitted change list — @baud's desktop card contract, served.

    THE CONTRACT IS THEIRS, read from their tree rather than invented here:
    GitChanges { files, count }, filled by `git diff HEAD --relative
    --name-only -- .`. Two consequences follow from that command, and both are
    reproduced deliberately:

        1. TRACKED FILES ONLY. `diff HEAD` cannot see a file git has never
           seen, so a brand-new module does not move the card's badge. That is
           @baud's call for the per-card question — their whole-project total
           asks the wider one on purpose — and a phone that counted differently
           would disagree with the desktop about the same branch at the same
           moment, with the phone being the one that was wrong.
        2. BRANCH-LOCAL NAMES. --relative keeps the rows local to the branch
           directory. Every src/aipass branch shares one repo, so a
           repo-relative name would prefix every row with the same characters
           and push the part that differs off a phone screen.

    `untracked` rides alongside as a COUNT, never folded into theirs. Matching
    a contract is not a reason to throw away something already measured, and
    @baud's own argument for their project total — that a count hiding a new
    module reads as false calm — does not stop being true here.

    GIT IS DRONE-ONLY, servers included. This shells `drone @git status`, the
    same door /v1/diff uses, and reads the porcelain codes drone passes through
    verbatim. It is a rendered surface and this file says so: drone publishes
    get_branch_status(), which already returns {ok, files, total}, but only
    from apps/handlers — not from drone's public package surface, and reaching
    into another branch's internals is the layering mistake this package has
    made once already. A --json on `drone @git status`, or that function
    published, retires every line of parsing below. It has been asked for.

    Args:
        branch: Branch name, resolved through the same two doors as every
            other read — the local citizen registry for the seat, @baud's
            census for any foreign project.
        project: Optional project name. Empty means the seat.

    Returns:
        Dict with branch, files (branch-local paths), count, and untracked.

    Raises:
        ReadRefused: Unknown branch, or a project with no such branch.
        ReadUnavailable: drone could not be run, timed out, or refused the
            command — including the case where drone declines to verify a
            caller outside an AIPass citizen directory, which is every foreign
            project. An empty change list would paint such a branch as clean
            when nothing was ever measured, so their sentence travels instead.
    """
    root = resolve_branch_root(branch, project)

    try:
        result = subprocess.run(
            ["drone", "@git", "status"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] drone not found for the git-changes lane: %s", e)
        raise ReadUnavailable("drone is not available on PATH — the git lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] git status timed out for %s after %ss", branch, DIFF_TIMEOUT_SECONDS)
        raise ReadUnavailable(f"Git status timed out after {DIFF_TIMEOUT_SECONDS}s") from e

    if result.returncode != 0:
        # drone exits non-zero on a failed status precisely so a caller cannot
        # read an error as a clean tree — their own fix, for a bug that
        # false-greened scripts for months. Honouring it is the whole point.
        stderr = (result.stderr or "").strip()
        logger.warning("[host_api] git status returned %s for %s: %s", result.returncode, branch, stderr)
        raise ReadUnavailable(f"Git status failed: {stderr or 'no detail'}")

    files, untracked = _changed_files(result.stdout or "", root)

    json_handler.log_operation(
        "host_api_git_changes_read",
        {"branch": branch, "count": len(files), "untracked": untracked},
    )

    return {
        "branch": branch,
        "files": files,
        "count": len(files),
        "untracked": untracked,
    }


def _changed_files(stdout: str, root: Path) -> Any:
    """
    Split drone's rendered status into the card's file list and a spare count.

    Args:
        stdout: `drone @git status` output — a header line, one line per file
            shaped `f"  {status:>2} {path}"`, and a scope footer.
        root: The branch directory, used to make repo-relative paths local.

    Returns:
        (files, untracked) — tracked paths that differ from HEAD, named
        relative to the branch, and how many untracked ones were set aside.

    Note:
        A line qualifies on STRUCTURE, not on prose: it must carry the indent
        and a non-empty status code where porcelain puts one. drone's header
        and footer are ordinary sentences and fail that test without this
        function needing to know a word of what they say — which is what keeps
        a reworded footer from becoming a phantom changed file.
    """
    prefix = _repo_relative_prefix(root)
    files = []
    untracked = 0

    for line in stdout.splitlines():
        if not line.startswith(STATUS_INDENT):
            continue

        code = line[STATUS_CODE_SLICE].strip()
        path = line[STATUS_PATH_FROM:].strip()
        if not code or not path:
            continue

        if code == UNTRACKED_CODE:
            untracked += 1
            continue

        if code == IGNORED_CODE:
            continue

        # A rename is one line naming two paths. The card shows the name the
        # file has NOW: passing the arrow through would put ' -> ' inside a
        # filename, and a phone tapping the row would ask for a file that
        # cannot exist.
        if RENAME_ARROW in path:
            path = path.split(RENAME_ARROW)[-1].strip()

        files.append(_branch_local(path, prefix))

    return files, untracked


def _repo_relative_prefix(root: Path) -> str:
    """
    The branch's path as drone's status lines spell it, ready to strip.

    Args:
        root: The branch directory.

    Returns:
        A posix prefix ending in '/', or '' when the branch is not inside this
        server's repo — a foreign project, where drone's paths are relative to
        a root this server has no business assuming.
    """
    try:
        return root.resolve().relative_to(repo_root().resolve()).as_posix() + "/"
    except ValueError:
        # A branch outside this server's repo — every foreign project. Names
        # then stay exactly as drone printed them, because the root they are
        # relative to is not one this server gets to assume. Logged rather
        # than swallowed: if this fires for a SEATED branch, the seat itself
        # has moved, and silently un-prefixed rows would be the only symptom.
        logger.info("[host_api] %s is outside this repo — git paths stay as drone printed them", root)
        return ""


def _branch_local(path: str, prefix: str) -> str:
    """
    One repo-relative path, made local to the branch like --relative does.

    Args:
        path: The path as drone printed it.
        prefix: The branch's repo-relative prefix, possibly empty.

    Returns:
        The branch-local name, or the path untouched when it does not sit
        under the prefix — never a guess, and never a silently mangled name.
    """
    if prefix and path.startswith(prefix):
        return path[len(prefix) :]
    return path
