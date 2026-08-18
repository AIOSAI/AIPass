# =================== AIPass ====================
# Name: git_reads.py
# Description: Host API Git Read Handler — the patch, the change list, the log, one commit
# Version: 1.0.0
# Created: 2026-08-17
# Modified: 2026-08-17
# =============================================

"""
Host API Git Read Handler

The repository-shaped half of the phone's read lane: what changed, what a patch
says, what was committed and by whom. Split out of reads.py, which had absorbed
the whole surface and crossed the 1500-line cap; the seam is the one @devpulse
named — repository reads here, file and directory reads there.

WHAT MAKES THIS A MODULE AND NOT A SECTION. Every lane in here answers by
running @drone's own door and parsing what comes back, so the whole file lives
under one discipline: parse on STRUCTURE, never on prose. Patch blocks are found
by their file headers, commits by a hex sha at the head of a row, changes by
porcelain's own two-column codes. A reworded footer upstream can then never
become a phantom file. reads.py answers from the filesystem directly and needs
none of that.

GRAIN. Every answer here names its own scope. Branch grain means the seat's own
subtree; repo grain means the whole repository the branch lives in. A log and a
commit are ALWAYS repo grain — a commit does not belong to a directory — and
they say so in the answer rather than leaving the caller to assume.

D0 holds: this server owns the pipe and never the meaning. The sentences that
come back travel verbatim.

Functions:
    read_diff()        - A patch: working tree, whole repo, one commit, or one file of one
    read_git_changes() - Changed files, at branch grain or repo grain
    read_git_log()     - The repository's recent commits
    read_commit()      - One commit's facts and per-file stat list
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

# The resolution half of the read lane. One direction only: repository reads
# lean on the name fence, never the other way round.
from aipass.api.apps.handlers.host.reads import (
    GRAIN_BRANCH,
    GRAIN_REPO,
    GRAINS,
    ReadRefused,
    ReadUnavailable,
    repo_root,
    repository_of,
    resolve_branch_root,
)

# Diffs are generated, not stored, so they carry the same 512KB ceiling the
# file read answers with. A cap that is hit is REPORTED, never a silent
# truncation.
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

    for base in (repository_of(resolved), repo_root()):
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
