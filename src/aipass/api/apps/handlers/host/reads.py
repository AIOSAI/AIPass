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
    read_diff()           - A patch: working tree, whole repo, or one commit's git read lane
    read_git_changes()    - Changed files, at branch grain or repo grain
    read_git_log()        - The repository's recent commits
    read_commit()         - One commit's facts and per-file stat list
    read_git_remote()     - The repository's remote, for link-cards out
    seated_project()      - The project this server is seated in
"""

import configparser
import subprocess
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

# Two grains, both honest, and every answer names its own. The card asks about
# one branch; the app asks about the repository the branch lives in (Patrick's
# ruling, DPLAN-0303 08-17). A lane that served one while a caller believed the
# other would be wrong in the most expensive way — silently.
GRAIN_BRANCH = "branch"
GRAIN_REPO = "repo"
GRAINS = (GRAIN_BRANCH, GRAIN_REPO)

# drone's own word for "the whole repository": _handle_diff and the status door
# both switch their target to lock_handler.find_repo_root() when they see it.
ALL_FLAG = "--all"

# Unified-diff structure. These are the machine framing, not prose, and they are
# the only things the per-file split and the +/- count are keyed on.
FILE_HEADER = "diff --git "
OLD_FILE_MARKER = "--- "
NEW_FILE_MARKER = "+++ "
HUNK_MARKER = "@@"
DEV_NULL = "/dev/null"
OLD_PREFIX = "a/"
NEW_PREFIX = "b/"

# The commit header, which is the default --pretty=medium framing: three labels
# and a message indented four spaces for display.
COMMIT_HEADER = "commit "
AUTHOR_HEADER = "Author: "
DATE_HEADER = "Date:"
MESSAGE_INDENT = "    "
COMMIT_LABELS = ((COMMIT_HEADER, "sha"), (AUTHOR_HEADER, "author"), (DATE_HEADER, "date"))

# A commit list is for a phone. 50 rows is @devpulse's number from the design.
# The repository marker, which is a DIRECTORY in an ordinary clone and a FILE
# in a worktree — the shape that has already bitten one lane in this file.
GIT_MARKER = ".git"
CONFIG_FILE = "config"
GITDIR_PREFIX = "gitdir:"
COMMONDIR_FILE = "commondir"

# Configuration names a remote as a subsection: remote "origin".
REMOTE_SECTION_PREFIX = "remote "
REMOTE_URL_KEY = "url"
DEFAULT_REMOTE = "origin"

# Remote URL forms. ssh has no browsable shape of its own, so it is the only
# family converted; http already is one and is left exactly as configured.
SCHEME_SEPARATOR = "://"
BROWSABLE_SCHEMES = ("http", "https")
SSH_SCHEMES = ("ssh", "git", "git+ssh")
WEB_SCHEME = "https"
CLONE_SUFFIX = ".git"
REDACTION = "***"

MAX_LOG_COMMITS = 50
DEFAULT_LOG_COMMITS = 20

# What a revision may be made of — names, paths, HEAD~3, HEAD^, tags, reflog
# braces — and nothing else. A leading dash is refused separately because it is
# an ordinary character mid-name and an option at the front.
SAFE_REF_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/~^@{}-")
MAX_REF_LENGTH = 200
MIN_SHA_LENGTH = 7
MAX_SHA_LENGTH = 40
HEX_CHARS = frozenset("0123456789abcdef")


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


def read_diff(
    branch: str,
    staged: bool = False,
    project: str = "",
    path: str = "",
    grain: str = "",
    ref: str = "",
) -> Dict[str, Any]:
    """
    Read a patch: a branch's working tree, the repository's, or one commit's.

    Everything here routes through drone — the house rule, and not one this
    server gets to bend because it happens to be a server. The command runs with
    the branch as its working directory, exactly as an operator would.

    THE MEASURED DOORS, 2026-08-17, because the design asked for two things that
    are not on the other side:

        _handle_diff recognises exactly --staged and --all. There is NO path
        parameter and NO -U passthrough. So `path` is served by generating the
        patch and splitting it HERE, on the per-file headers, and the context
        width is whatever the door generates — three lines, not the one line the
        design preferred. Asked of @drone; unreachable until then, and saying so
        is cheaper than a phone quietly rendering a width nobody chose.

    Args:
        branch: Branch name, resolved through the registry.
        staged: Whether to ask for the staged patch. Meaningless with a ref.
        project: Optional project name. Empty means the seat; any project
            @baud's census knows is served.
        path: Optional single file. Empty means the whole patch. A file with no
            changes is REFUSED in words rather than answered with "".
        grain: branch (the default) or repo. A commit is always repo.
        ref: Optional commit. Empty means the working tree.

    Returns:
        Dict with branch, grain, staged, ref, path, bytes, truncated and diff.

    Raises:
        ReadRefused: Unknown branch, unknown grain, a garbage ref, an impossible
            combination, or a file this patch does not touch.
        ReadUnavailable: drone could not be run, timed out, or failed.
    """
    if ref:
        ref = _checked_ref(ref)

        # Silently ignoring a parameter is a lie told by omission. A caller who
        # asked for something a commit cannot have is told why, not answered
        # with something else that happens to be available.
        if grain and grain != GRAIN_REPO:
            raise ReadRefused(f"A commit is repo-wide by construction — {grain!r} grain cannot be asked of {ref}")
        if staged:
            raise ReadRefused(f"A commit has no staging area — staged cannot be asked of {ref}")

        grain = GRAIN_REPO
    else:
        grain = _checked_grain(grain)

    root = resolve_branch_root(branch, project)
    command = _patch_command(staged=staged, grain=grain, ref=ref)

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

    if ref:
        # The header belongs to the commit lane. A renderer handed it would
        # paint a phantom first file named after the word 'commit'.
        diff = _patch_of(diff)

    if path:
        diff = _one_files_patch(diff, path)

    raw_bytes = len(diff.encode("utf-8"))
    truncated = False

    if raw_bytes > MAX_DIFF_BYTES:
        if path:
            # Half a patch is not a small patch, it is a broken one: a severed
            # hunk renders as nonsense. A whole tree can degrade because a wall
            # of text still reads as a wall of text; one file cannot.
            raise ReadRefused(f"{path} is {raw_bytes} bytes of patch, over the {MAX_DIFF_BYTES} byte cap")

        # A patch is generated, so capping it is reasonable — but the cap is
        # REPORTED. No silent truncation reading as a complete patch.
        truncated = True
        diff = diff.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore")
        logger.info("[host_api] diff for %s truncated at %d bytes", branch, MAX_DIFF_BYTES)

    json_handler.log_operation(
        "host_api_diff_read",
        {
            "branch": branch,
            "grain": grain,
            "staged": staged,
            "ref": ref,
            "path": path,
            "bytes": raw_bytes,
            "truncated": truncated,
        },
    )

    return {
        "branch": branch,
        "grain": grain,
        "staged": staged,
        "ref": ref,
        "path": path,
        "bytes": raw_bytes,
        "truncated": truncated,
        "diff": diff,
    }


def _patch_command(staged: bool, grain: str, ref: str) -> Any:
    """
    The drone command for a patch — only the flags its door actually recognises.

    Args:
        staged: Whether the staged patch was asked for.
        grain: Which scope, already checked.
        ref: A commit, or empty for the working tree.

    Returns:
        The argv list to run.
    """
    if ref:
        return ["drone", "@git", "show", ref]

    command = ["drone", "@git", "diff"]

    if staged:
        command.append("--staged")

    if grain == GRAIN_REPO:
        command.append(ALL_FLAG)

    return command


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


def read_git_changes(branch: str, project: str = "", grain: str = "") -> Dict[str, Any]:
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
        grain: branch (the default) for the card's question, or repo for the
            app's — every changed file in the repository the branch lives in,
            which is a scope no single card can honestly show.

    Returns:
        Dict with branch, grain, files, count, untracked, and rows. At branch grain
        the names are branch-local; at repo grain they stay repo-relative,
        because there the prefix IS the part that differs between branches.

    Raises:
        ReadRefused: Unknown branch, or a project with no such branch.
        ReadUnavailable: drone could not be run, timed out, or refused the
            command — including the case where drone declines to verify a
            caller outside an AIPass citizen directory, which is every foreign
            project. An empty change list would paint such a branch as clean
            when nothing was ever measured, so their sentence travels instead.
    """
    grain = _checked_grain(grain)
    root = resolve_branch_root(branch, project)

    command = ["drone", "@git", "status"]
    if grain == GRAIN_REPO:
        # drone's own flag for the repository root — the app's question.
        command.append(ALL_FLAG)

    try:
        result = subprocess.run(
            command,
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

    # At repo grain the paths already ARE repo-relative, so there is no prefix
    # to strip — stripping one would eat the very part that distinguishes one
    # branch's file from another's, which is all the app is there to show.
    files, untracked, rows = _changed_files(result.stdout or "", root if grain == GRAIN_BRANCH else None)

    json_handler.log_operation(
        "host_api_git_changes_read",
        {"branch": branch, "grain": grain, "count": len(files), "untracked": untracked},
    )

    return {
        "branch": branch,
        "grain": grain,
        "files": files,
        "count": len(files),
        "untracked": untracked,
        "rows": rows,
    }


def _changed_files(stdout: str, root: Optional[Path]) -> Any:
    """
    Split drone's rendered status into the card's file list and a spare count.

    Args:
        stdout: `drone @git status` output — a header line, one line per file
            shaped `f"  {status:>2} {path}"`, and a scope footer.
        root: The branch directory, used to make repo-relative paths local —
            or None at repo grain, where those names ARE the answer.

    Returns:
        (files, untracked, rows) — tracked paths that differ from HEAD named
        relative to the branch, how many untracked ones were set aside, and
        EVERY changed path with git's own two-column code beside it.

        `rows` is additive and `files` is untouched by it: @baud's desktop
        consumer parses the older pair, and untracked names appearing in the
        tracked list is exactly the disagreement this lane exists to avoid.
        The code travels VERBATIM AND UNSTRIPPED — the two columns are index
        then worktree, so 'A ' (staged new) and ' M' (modified, unstaged) are
        different answers that collapse into one letter the moment either is
        trimmed. @devpulse measured that collapse from the face: of four VS
        Code chips only two could be built. Which code means which chip is
        THEIR decision, made once in their buildRows; a letter invented here
        would be a second vocabulary for a fact git has already stated.

    Note:
        A line qualifies on STRUCTURE, not on prose: it must carry the indent
        and a non-empty status code where porcelain puts one. drone's header
        and footer are ordinary sentences and fail that test without this
        function needing to know a word of what they say — which is what keeps
        a reworded footer from becoming a phantom changed file.
    """
    prefix = _repo_relative_prefix(root) if root is not None else ""
    files = []
    rows = []
    untracked = 0

    for line in stdout.splitlines():
        if not line.startswith(STATUS_INDENT):
            continue

        # UNSTRIPPED: the two columns are the answer, not noise around it.
        code = line[STATUS_CODE_SLICE]
        path = line[STATUS_PATH_FROM:].strip()
        if not code.strip() or not path:
            continue

        if code.strip() == IGNORED_CODE:
            # Ignored is not a change. It is in no list, old or new.
            continue

        # A rename is one line naming two paths. The card shows the name the
        # file has NOW: passing the arrow through would put ' -> ' inside a
        # filename, and a phone tapping the row would ask for a file that
        # cannot exist.
        if RENAME_ARROW in path:
            path = path.split(RENAME_ARROW)[-1].strip()

        local = _branch_local(path, prefix)
        rows.append({"path": local, "status": code})

        if code.strip() == UNTRACKED_CODE:
            untracked += 1
            continue

        files.append(local)

    return files, untracked, rows


def _repo_relative_prefix(root: Path) -> str:
    """
    The branch's path as drone's status lines spell it, ready to strip.

    Args:
        root: The branch directory.

    Returns:
        A posix prefix ending in '/', or '' when nothing above the branch marks
        a repository and no prefix could be stripped honestly.

    Note:
        DISCOVERY FIRST, the seat only as a fallback. Paths are reported
        relative to the repository found by walking up for a '.git' marker, so
        that is the only prefix guaranteed to match what drone printed. Trusting
        the seat's own root was wrong twice: a foreign project sits OUTSIDE it,
        and a nested one (projects/baud carries its own marker) sits INSIDE it
        while its rows are still reported against the inner repository. Both
        cases left every row un-stripped, which is the bug this order fixes.
    """
    resolved = root.resolve()

    for base in (_discovered_repo_root(resolved), repo_root()):
        prefix = _prefix_under(resolved, base)
        if prefix is not None:
            return prefix

    # Nothing above this branch marks a repository, so no prefix could be
    # stripped honestly. drone's names travel untouched rather than trimmed on
    # a guess — logged, because for a SEATED branch it would mean the seat
    # itself has moved and un-prefixed rows would be the only symptom.
    logger.info("[host_api] no repository root above %s — paths stay as drone printed them", root)
    return ""


def _prefix_under(path: Path, base: Optional[Path]) -> Optional[str]:
    """
    How to spell `path` relative to `base`, or None when it does not sit there.

    Args:
        path: The resolved branch directory.
        base: A candidate repository root, or None when there is no candidate.

    Returns:
        A posix prefix ending in '/', or None. None is a real answer here — "not
        under this root" is the question being asked, and the caller reads it as
        "try the next candidate".

    Note:
        Asked with is_relative_to rather than by catching relative_to's
        ValueError. Same result, but "is this under that?" is a question, not a
        failure, and a catch here reads as swallowing one.
    """
    if base is None:
        return None

    resolved_base = base.resolve()
    if not path.is_relative_to(resolved_base):
        return None

    return path.relative_to(resolved_base).as_posix() + "/"


def _discovered_repo_root(root: Path) -> Optional[Path]:
    """
    The repository a branch actually sits in, found the way the tool does.

    Args:
        root: The resolved branch directory.

    Returns:
        The nearest ancestor carrying a '.git' marker, or None when there is
        none above this branch at all.

    Note:
        The marker is checked with exists(), not is_dir(): a worktree or a
        submodule carries it as a FILE, and reading those as "not a repository"
        would silently un-strip every row inside them.
    """
    for candidate in (root, *root.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


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


# ==============================================
# THE GIT APP
# ==============================================


def read_git_log(branch: str, project: str = "", limit: int = DEFAULT_LOG_COMMITS) -> Dict[str, Any]:
    """
    The repository's recent commits — a short object name and a subject.

    ALWAYS REPO GRAIN, and the answer says so. drone's log door runs from
    lock_handler.find_repo_root() with no pathspec, so a branch names WHICH
    repository and never narrows the history to itself. Reporting branch grain
    here would be a straight lie about what was measured.

    MEASURED GAP, 2026-08-17: that door is --oneline, so a row carries an object
    name and a subject and NOTHING else. No author, no date, however much a
    design asks for them — those live in the commit door, one commit at a time,
    and fifty subprocesses each dragging a whole patch is not a list lane. Asked
    of @drone; until then this ships what exists instead of inventing it.

    Args:
        branch: Branch name — which repository, not which history.
        project: Optional project name. Empty means the seat.
        limit: How many commits, 1 to MAX_LOG_COMMITS.

    Returns:
        Dict with branch, grain, commits (sha and subject) and count.

    Raises:
        ReadRefused: Unknown branch, or a limit outside the served range.
        ReadUnavailable: drone could not be run, timed out, or failed.
    """
    if limit < 1 or limit > MAX_LOG_COMMITS:
        # Clamping in silence would hand 50 rows to a caller who asked for 500
        # and let them believe that was all the history there is.
        raise ReadRefused(f"Asked for {limit} commits — this lane serves 1 to {MAX_LOG_COMMITS}")

    root = resolve_branch_root(branch, project)

    try:
        result = subprocess.run(
            ["drone", "@git", "log", str(limit)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] drone not found for the log lane: %s", e)
        raise ReadUnavailable("drone is not available on PATH — the log lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] log timed out for %s after %ss", branch, DIFF_TIMEOUT_SECONDS)
        raise ReadUnavailable(f"Log timed out after {DIFF_TIMEOUT_SECONDS}s") from e

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        logger.warning("[host_api] log returned %s for %s: %s", result.returncode, branch, stderr)
        raise ReadUnavailable(f"Log failed: {stderr or 'no detail'}")

    commits = _commits_of(result.stdout or "")

    json_handler.log_operation(
        "host_api_git_log_read",
        {"branch": branch, "limit": limit, "count": len(commits)},
    )

    return {
        "branch": branch,
        "grain": GRAIN_REPO,
        "commits": commits,
        "count": len(commits),
    }


def read_commit(branch: str, ref: str, project: str = "") -> Dict[str, Any]:
    """
    One commit's facts and its per-file stat list — never its patch.

    The patch is the diff lane's job, one file at a time, precisely so a phone
    never loads a whole commit at once. This lane answers who, when, what it
    said, and which files moved by how much.

    Args:
        branch: Branch name — which repository the commit is read from.
        ref: The revision. Checked before any subprocess exists.
        project: Optional project name. Empty means the seat.

    Returns:
        Dict with ref, sha, author, date, subject, message, files (path,
        additions, deletions) and count.

    Raises:
        ReadRefused: Unknown branch, or a ref outside a revision's vocabulary.
        ReadUnavailable: drone could not be run, timed out, or could not read
            the commit — an unknown object included, in their own words.
    """
    ref = _checked_ref(ref)
    root = resolve_branch_root(branch, project)

    try:
        result = subprocess.run(
            ["drone", "@git", "show", ref],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] drone not found for the commit lane: %s", e)
        raise ReadUnavailable("drone is not available on PATH — the commit lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] commit read timed out for %s after %ss", ref, DIFF_TIMEOUT_SECONDS)
        raise ReadUnavailable(f"Commit read timed out after {DIFF_TIMEOUT_SECONDS}s") from e

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        logger.warning("[host_api] commit read returned %s for %s: %s", result.returncode, ref, stderr)
        raise ReadUnavailable(f"Commit read failed: {stderr or 'no detail'}")

    shown = result.stdout or ""
    facts = _commit_facts(shown)
    files = []

    for block in _per_file_blocks(_patch_of(shown)):
        additions, deletions = _stat_of_block(block)
        files.append({"path": _path_of_block(block), "additions": additions, "deletions": deletions})

    json_handler.log_operation(
        "host_api_commit_read",
        {"ref": ref, "sha": facts["sha"], "count": len(files)},
    )

    return {
        "ref": ref,
        "sha": facts["sha"],
        "author": facts["author"],
        "date": facts["date"],
        "subject": facts["subject"],
        "message": facts["message"],
        "files": files,
        "count": len(files),
    }


def _checked_grain(grain: str) -> str:
    """
    Which scope was asked for, or a refusal naming both.

    A typo must never fall through to a scope the caller did not ask for: that is
    how a phone shows one branch's changes while believing it shows a whole
    repository's, with nothing anywhere reading as wrong.

    Args:
        grain: The asked-for scope. Empty means the branch, the older default.

    Returns:
        The scope to serve.

    Raises:
        ReadRefused: Anything that is not one of the two served scopes.
    """
    if not grain:
        return GRAIN_BRANCH

    if grain not in GRAINS:
        raise ReadRefused(f"Unknown grain {grain!r} — this lane serves {GRAIN_BRANCH} or {GRAIN_REPO}")

    return grain


def _checked_ref(ref: str) -> str:
    """
    A revision, or a refusal — decided before any subprocess exists.

    Args:
        ref: The caller's revision.

    Returns:
        The revision, stripped.

    Raises:
        ReadRefused: Empty, option-shaped, over-long, or carrying a character
            that has no place in a revision name.
    """
    candidate = ref.strip()

    if not candidate:
        raise ReadRefused("No commit was named")

    if candidate.startswith("-"):
        raise ReadRefused(f"Refusing {candidate!r} as a commit — a leading dash reads as an option, never a revision")

    if len(candidate) > MAX_REF_LENGTH:
        raise ReadRefused(f"Commit name is {len(candidate)} characters, over the {MAX_REF_LENGTH} cap")

    stray = sorted(set(candidate) - SAFE_REF_CHARS)
    if stray:
        raise ReadRefused(f"Refusing {candidate!r} as a commit — {''.join(stray)!r} has no place in a revision name")

    return candidate


def _patch_of(shown: str) -> str:
    """
    The patch inside a shown commit, without the header lines that frame it.

    Args:
        shown: The commit door's whole output.

    Returns:
        Everything from the first per-file header on, or "" for a commit that
        changed nothing — an empty or merge commit is still a commit.
    """
    lines = shown.splitlines(keepends=True)

    for index, line in enumerate(lines):
        if line.startswith(FILE_HEADER):
            return "".join(lines[index:])

    return ""


def _per_file_blocks(patch: str) -> Any:
    """
    Split a patch into one block per file, keyed on the per-file header.

    Args:
        patch: Unified patch text.

    Returns:
        A list of blocks, each starting with its own header so a renderer can
        still read the filename and the change kind out of it.
    """
    blocks: Any = []

    for line in patch.splitlines(keepends=True):
        if line.startswith(FILE_HEADER):
            blocks.append(line)
        elif blocks:
            blocks[-1] += line

    return blocks


def _one_files_patch(patch: str, path: str) -> str:
    """
    One file's block out of a patch, or a refusal naming the file.

    Args:
        patch: Unified patch text.
        path: The file asked for, matched EXACTLY against the block's own name —
            a substring match would answer for other_hello.txt when hello.txt
            was asked for, and the phone would show a different file's changes.

    Returns:
        That file's block.

    Raises:
        ReadRefused: The patch does not touch that file. An empty string would
            read as "no changes, rendered fine"; a tap on a stale list is a real
            event and gets a real sentence.
    """
    for block in _per_file_blocks(patch):
        if _path_of_block(block) == path:
            return block

    raise ReadRefused(f"No changes to {path} in this patch")


def _path_of_block(block: str) -> str:
    """
    Which file a block is about, read from the lines that name exactly one.

    Args:
        block: One file's patch block.

    Returns:
        The file's name, or "" if the header could not be read — which is logged
        rather than swallowed.

    Note:
        THE FIRST NAMING LINE WINS, and that ordering is the whole protection.
        Inside a hunk, removing a line that reads '-- x' produces exactly '--- x'
        and adding one that reads '++ x' produces exactly '+++ x' — both
        character-for-character the shape of a header. Neither can be mistaken
        for one, because a block's own header lines are emitted BEFORE its first
        hunk and this returns on them. A guard at the hunk marker was written
        first and then deleted: no mutation could kill it, which is what proved
        it unreachable rather than careful. The deleted side is read when the
        added side is /dev/null, which is what makes a deletion name its file.
    """
    for line in block.splitlines():
        if line.startswith(NEW_FILE_MARKER):
            named = line[len(NEW_FILE_MARKER) :].strip()
            if named != DEV_NULL:
                return named[len(NEW_PREFIX) :] if named.startswith(NEW_PREFIX) else named
        elif line.startswith(OLD_FILE_MARKER):
            named = line[len(OLD_FILE_MARKER) :].strip()
            if named != DEV_NULL:
                return named[len(OLD_PREFIX) :] if named.startswith(OLD_PREFIX) else named

    return _both_names(block)


def _both_names(block: str) -> str:
    """
    The fallback for a block with no per-line names — binary, or mode-only.

    Args:
        block: One file's patch block.

    Returns:
        The file's name, or "" when the halves never agree.

    Note:
        The header names the path TWICE, so the two halves confirm each other.
        That is what keeps a filename which itself contains the marker from
        splitting the header in the wrong place.
    """
    header = block.splitlines()[0][len(FILE_HEADER) :]
    marker = " " + NEW_PREFIX
    cut = header.find(marker)

    while cut != -1:
        left = header[:cut]
        right = header[cut + len(marker) :]
        if left.startswith(OLD_PREFIX) and left[len(OLD_PREFIX) :] == right:
            return right
        cut = header.find(marker, cut + 1)

    logger.info("[host_api] could not name the file in a patch header: %r", header[:200])
    return ""


def _stat_of_block(block: str) -> Any:
    """
    How many lines a block adds and removes, counted INSIDE its hunks only.

    Args:
        block: One file's patch block.

    Returns:
        (additions, deletions).

    Note:
        Counting only from the first hunk marker is what keeps the two file-header
        lines out of the total: they start with the same characters as a changed
        line, and counting them would add one phantom addition and one phantom
        deletion to every file in every commit.
    """
    additions = 0
    deletions = 0
    in_hunk = False

    for line in block.splitlines():
        if line.startswith(HUNK_MARKER):
            in_hunk = True
            continue

        if not in_hunk:
            continue

        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1

    return additions, deletions


def _commits_of(stdout: str) -> Any:
    """
    Rows from the log door's rendering: an object name, one space, a subject.

    Args:
        stdout: The log door's whole output.

    Returns:
        A list of {sha, subject}, newest first because that is the order given.

    Note:
        A row qualifies on STRUCTURE — it must LEAD with something shaped like an
        abbreviated object name — so a header or footer sentence cannot become a
        phantom commit, however it is worded. Splitting on the FIRST space is
        what keeps a colon-heavy subject intact.
    """
    commits = []

    for line in stdout.splitlines():
        sha, _, subject = line.strip().partition(" ")
        if not _looks_like_sha(sha) or not subject.strip():
            continue
        commits.append({"sha": sha, "subject": subject.strip()})

    return commits


def _looks_like_sha(token: str) -> bool:
    """
    Whether a token could be an abbreviated object name.

    Args:
        token: The first word of a row.

    Returns:
        True if it is hex and of a plausible length.
    """
    return MIN_SHA_LENGTH <= len(token) <= MAX_SHA_LENGTH and set(token) <= HEX_CHARS


def _commit_facts(shown: str) -> Dict[str, str]:
    """
    A commit's header, read on its label prefixes and its display indent.

    Args:
        shown: The commit door's whole output.

    Returns:
        Dict with sha, author, date, subject and message.

    Note:
        The FIRST line carrying a label wins. Anything else that is indented is
        message; a blank line is message only once there is a message for it to
        belong to, which is what keeps the gap under the header out of the body.
    """
    facts = {"sha": "", "author": "", "date": ""}
    message_lines = []

    for line in _header_lines(shown):
        key, value = _labelled(line)

        if key and not facts[key]:
            facts[key] = value
        elif line.startswith(MESSAGE_INDENT):
            # The indent is for DISPLAY. Passing it through would paint every
            # commit body on the phone as a code block.
            message_lines.append(line[len(MESSAGE_INDENT) :])
        elif not line.strip() and message_lines:
            message_lines.append("")

    message = "\n".join(message_lines).strip("\n")

    return {
        # First token only: a decorated header carries ref names after the sha.
        "sha": facts["sha"].split(" ")[0],
        "author": facts["author"],
        "date": facts["date"],
        "subject": message.splitlines()[0] if message else "",
        "message": message,
    }


def _header_lines(shown: str) -> Any:
    """
    Every line of a shown commit before its patch begins.

    Args:
        shown: The commit door's whole output.

    Returns:
        The header lines. The scan stops dead at the first per-file header:
        after that a four-space line is somebody's source code, not a word of
        any commit message.
    """
    lines = []

    for line in shown.splitlines():
        if line.startswith(FILE_HEADER):
            break
        lines.append(line)

    return lines


def _labelled(line: str) -> Any:
    """
    Which header field a line carries, if any.

    Args:
        line: One header line.

    Returns:
        (key, value), or ("", "") for a line carrying no label at all.
    """
    for prefix, key in COMMIT_LABELS:
        if line.startswith(prefix):
            return key, line[len(prefix) :].strip()

    return "", ""


# ==============================================
# THE REMOTE
# ==============================================


def read_git_remote(branch: str, project: str = "") -> Dict[str, Any]:
    """
    The repository's remote — what the phone's link-cards are built from.

    THE DOOR WAS MEASURED BEFORE ANY OF THIS WAS DESIGNED, and there is none:
    no verb on drone's git surface, nothing on drone's public Python surface,
    and the fleet's own gate refuses BOTH raw readers because neither sits in
    its read-only allowlist. So this lane shells nothing at all and reads the
    repository's configuration as the INI file it is. That leaves the
    drone-only rule this package documents intact instead of quietly carving an
    exception into it for one lane. A verb on drone retires every line below,
    and it has been asked for.

    A REMOTE IS A REPOSITORY FACT, so the grain says repo and the branch names
    WHICH repository — the same vocabulary the log and commit lanes use.

    Args:
        branch: Branch name, resolved through the same two doors as every other
            read — the local citizen registry for the seat, @baud's census for
            any foreign project.
        project: Optional project name. Empty means the seat.

    Returns:
        Dict with branch, grain, remote (which one answered), url (as
        configured, any password redacted), web (a browsable form, or None) and
        redacted.

    Raises:
        ReadRefused: Unknown branch, or a repository with no remote at all —
            which is not hypothetical, two projects in the real tree have none.
        ReadUnavailable: No repository above the branch, an unreadable
            configuration, or a worktree pointer leading nowhere.
    """
    root = resolve_branch_root(branch, project)
    configuration = _repository_config(root)
    name, configured = _configured_remote(configuration)
    url, redacted = _without_credentials(configured)

    json_handler.log_operation(
        "host_api_git_remote_read",
        # The URL itself never reaches an audit line: it is the one field here
        # that can carry a secret, and a redacted copy is still not a fact worth
        # writing to disk on every read.
        {"branch": branch, "remote": name, "redacted": redacted},
    )

    return {
        "branch": branch,
        "grain": GRAIN_REPO,
        "remote": name,
        "url": url,
        "web": _browsable(configured),
        "redacted": redacted,
    }


def _repository_config(root: Path) -> Path:
    """
    The configuration file of the repository a branch lives in.

    Args:
        root: The branch directory.

    Returns:
        Path to the configuration file.

    Raises:
        ReadUnavailable: No repository above it, or no readable configuration.
    """
    repository = _discovered_repo_root(root.resolve())

    if repository is None:
        raise ReadUnavailable(f"No repository above {root.name} — nothing here has a remote to name")

    marker = repository / GIT_MARKER
    directory = marker if marker.is_dir() else _pointed_at(marker)
    configuration = directory / CONFIG_FILE

    if not configuration.is_file():
        raise ReadUnavailable(f"The repository above {root.name} has no readable configuration")

    return configuration


def _pointed_at(marker: Path) -> Path:
    """
    Follow a worktree's pointer file to the directory that holds configuration.

    Args:
        marker: The repository marker, here a FILE rather than a directory.

    Returns:
        The directory whose configuration governs this tree.

    Raises:
        ReadUnavailable: The file points nowhere, or points at something absent.
            A fallback here would invent a repository, which is worse than a
            503 that names what was actually found.

    Note:
        A worktree's own directory holds NO configuration — the repository it
        was cut from does, and commondir is the pointer across to it. Following
        only the first hop would answer with a file that is not there.
    """
    text = marker.read_text(encoding="utf-8", errors="replace").strip()

    if not text.startswith(GITDIR_PREFIX):
        raise ReadUnavailable(f"{marker.name} is a file, but it does not point anywhere")

    pointed = Path(text[len(GITDIR_PREFIX) :].strip())
    if not pointed.is_absolute():
        pointed = marker.parent / pointed

    if not pointed.is_dir():
        raise ReadUnavailable(f"{marker.name} points at {pointed}, which is not there")

    shared = pointed / COMMONDIR_FILE
    if not shared.is_file():
        return pointed

    common = Path(shared.read_text(encoding="utf-8", errors="replace").strip())
    if not common.is_absolute():
        common = pointed / common

    if not common.is_dir():
        raise ReadUnavailable(f"{COMMONDIR_FILE} points at {common}, which is not there")

    return common.resolve()


def _configured_remote(configuration: Path) -> Any:
    """
    Which remote answers for this repository, and the URL it carries.

    Args:
        configuration: Path to the repository's configuration file.

    Returns:
        (name, url).

    Raises:
        ReadRefused: No remote is configured at all. An empty string would
            render as a link card pointing nowhere.
        ReadUnavailable: The configuration could not be parsed.

    Note:
        origin wins by convention when several exist, but the name TRAVELS
        either way — refusing a repository that simply called its remote
        something else would be this lane inventing a rule that does not exist,
        and answering silently would make the choice invisible to the caller.
    """
    parser = configparser.ConfigParser(strict=False)

    try:
        parser.read(configuration, encoding="utf-8")
    except configparser.Error as e:
        logger.error("[host_api] repository configuration would not parse: %s", e)
        raise ReadUnavailable(f"The repository configuration could not be read: {e}") from e

    remotes = []
    for section in parser.sections():
        if not section.startswith(REMOTE_SECTION_PREFIX):
            continue
        url = parser.get(section, REMOTE_URL_KEY, fallback="").strip()
        if not url:
            continue
        remotes.append((section[len(REMOTE_SECTION_PREFIX) :].strip().strip('"'), url))

    if not remotes:
        raise ReadRefused("This repository has no remote configured — there is no forge to link to")

    for name, url in remotes:
        if name == DEFAULT_REMOTE:
            return name, url

    return remotes[0]


def _without_credentials(url: str) -> Any:
    """
    The configured URL with any password replaced, and whether one was there.

    Args:
        url: The URL exactly as configured.

    Returns:
        (url, redacted).

    Note:
        THIS WAS NOT IN THE ASK. A remote may carry user:token@ — that is how a
        machine clones a private repository with no human present — and this
        lane's whole job is handing that URL to a client over a network. The
        user survives so an operator still recognises their own configuration;
        only the secret half is replaced, and the boolean is what stops the
        change being silent. A bare user with no colon is the standard ssh form
        and carries no secret: flagging it would cry wolf on the commonest
        remote there is, and an alarm that fires on everything is unread.
    """
    separator = url.find(SCHEME_SEPARATOR)
    if separator == -1:
        return url, False

    scheme = url[:separator]
    rest = url[separator + len(SCHEME_SEPARATOR) :]

    at = rest.rfind("@")
    if at == -1:
        return url, False

    userinfo = rest[:at]
    if ":" not in userinfo:
        return url, False

    user = userinfo.split(":", 1)[0]
    logger.info("[host_api] a credential in a remote URL was redacted before it left this process")

    return f"{scheme}{SCHEME_SEPARATOR}{user}:{REDACTION}@{rest[at + 1 :]}", True


def _browsable(url: str) -> Optional[str]:
    """
    A URL a person can open, or None when there honestly is not one.

    Args:
        url: The URL exactly as configured.

    Returns:
        The browsable form, or None for anything that is not a web address —
        a filesystem path is a directory, not a page, and putting a scheme in
        front of one would be a link card leading somewhere never existed.
    """
    scheme, host, path = _url_parts(url)

    if scheme is None:
        return None

    if scheme in BROWSABLE_SCHEMES:
        # http is NOT upgraded. ssh has no browsable form of its own so
        # converting it is forced; http already is one, and changing it would be
        # this lane deciding something about a host it cannot know.
        target = scheme
    elif scheme in SSH_SCHEMES:
        target = WEB_SCHEME
    else:
        logger.info("[host_api] no browsable form for a %r remote", scheme)
        return None

    trimmed = path[: -len(CLONE_SUFFIX)] if path.endswith(CLONE_SUFFIX) else path

    return f"{target}{SCHEME_SEPARATOR}{host}/{trimmed}"


def _url_parts(url: str) -> Any:
    """
    Split a remote URL into scheme, host and path.

    Args:
        url: The URL exactly as configured.

    Returns:
        (scheme, host, path), or (None, "", "") for anything with no host in it.
        Any userinfo is dropped here — a browsable link needs no identity, and
        this is the one place that guarantees none reaches one.
    """
    separator = url.find(SCHEME_SEPARATOR)

    if separator == -1:
        return _short_form_parts(url)

    scheme = url[:separator]
    authority, _, path = url[separator + len(SCHEME_SEPARATOR) :].partition("/")

    return scheme, authority.rsplit("@", 1)[-1], path


def _short_form_parts(url: str) -> Any:
    """
    The scp-like form, host-colon-path, told apart from a filesystem path.

    Args:
        url: The URL exactly as configured.

    Returns:
        (scheme, host, path), or (None, "", "").

    Note:
        THE TRAP: a Windows path carries a colon too, so both halves are checked
        rather than assumed. The host half may hold no separator and the path
        half may not START with one — which is exactly what a drive letter
        followed by a backslash does, and reading that as a host would emit a
        link card pointing at a machine named C.
    """
    host_part, separator, path = url.partition(":")

    if not separator or not path:
        return None, "", ""

    if "/" in host_part or "\\" in host_part:
        return None, "", ""

    if path[0] in ("/", "\\"):
        return None, "", ""

    host = host_part.rsplit("@", 1)[-1]
    if not host:
        return None, "", ""

    return WEB_SCHEME, host, path
