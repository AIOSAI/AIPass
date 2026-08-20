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
running @drone's own door, so the whole file lives under one discipline: read
the MACHINE surface, never the rendered one. Since 2026-08-18 that means --json
on every door that has it — status, log, show, remote — and the document's own
`ok` verdict decides whether an answer is a refusal. Only the patch itself is
still text, because a patch IS text: its per-file headers and hunk markers are
git's own machine framing, and those are parsed on structure, never on prose.
reads.py answers from the filesystem directly and needs none of this.

WHY THE RENDERED SURFACE WAS NOT GOOD ENOUGH, measured 2026-08-18. drone's
status renderer right-aligns the porcelain code into two columns — their own
comment calls it "for the screen only" — so every INDEX-only change arrives
looking like a WORKTREE one: 'A ' as ' A', 'M ' as ' M', 'D ' as ' D'. This
lane read that and passed it on, which meant a staged file and an unstaged one
were the same answer here for as long as rows have existed. No amount of
careful parsing could have recovered it; the columns were gone before this
process saw them. The document carries index and worktree separately, and that
is the whole reason this file no longer reads a rendered line anywhere.

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
    read_git_remote()  - The repository's remote, for the phone's link-cards
"""

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import refusals as host_refusals

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

# THE MACHINE DOOR. Asking for it is what makes every lane below a reader of
# facts rather than of sentences, and it is not optional politeness: the
# rendered surface cannot express the difference between a staged change and an
# unstaged one (see the note in the module docstring), so a lane without this
# flag is a lane that cannot be correct however well it parses.
JSON_FLAG = "--json"

# The envelope every one of drone's --json git doors answers with. The verdict
# is theirs to give and ours to honour — never re-derived from an exit code.
OK_KEY = "ok"
MESSAGE_KEY = "message"

# The payload field each door fills, and the fields inside one row.
FILES_KEY = "files"
COMMITS_KEY = "commits"
REMOTES_KEY = "remotes"
CONTENT_KEY = "content"

STATUS_KEY = "status"
PATH_KEY = "path"
INDEX_KEY = "index"
WORKTREE_KEY = "worktree"
SHA_KEY = "sha"
SUBJECT_KEY = "subject"

# One remote's row. `fetch` is the URL a clone came from and the one a link-card
# is built on; `push` answers only when they genuinely differ.
NAME_KEY = "name"
FETCH_KEY = "fetch"
PUSH_KEY = "push"
REDACTED_KEY = "redacted"
DEFAULT_REMOTE = "origin"

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

# A remote URL's shape, and what may be shown of one. THE REDACTION STAYS EVEN
# THOUGH DRONE REDACTS TOO: this is the last process a URL passes through before
# it crosses a network, and a doctrine that only holds while upstream keeps
# holding it is not a doctrine. Belt and braces, cheap, and pinned by its own
# tests against what THIS surface emits — never against what upstream sent.
SCHEME_SEPARATOR = "://"
BROWSABLE_SCHEMES = ("http", "https")
SSH_SCHEMES = ("ssh", "git", "git+ssh")
WEB_SCHEME = "https"
CLONE_SUFFIX = ".git"
REDACTION = "***"


def _ran(command: Any, root: Path, lane: str) -> Any:
    """
    Run one of drone's doors, or fail in words naming which lane could not.

    Args:
        command: The argv list.
        root: The directory to run in — the branch, exactly as an operator
            standing in it would.
        lane: The lane's own name, for a message a reader can act on.

    Returns:
        The completed process, whatever its exit code. Reading the OUTCOME is
        the caller's job: for a --json door that is the document's verdict, and
        for the patch door it is the exit code, because there is no document.

    Raises:
        ReadUnavailable: drone could not be run at all, or did not finish.
    """
    try:
        return subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] drone not found for the %s lane: %s", lane, e)
        raise ReadUnavailable(f"drone is not available on PATH — the {lane} lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] the %s lane timed out after %ss", lane, DIFF_TIMEOUT_SECONDS)
        raise ReadUnavailable(f"The {lane} lane timed out after {DIFF_TIMEOUT_SECONDS}s") from e


def _document(command: Any, root: Path, lane: str) -> Dict[str, Any]:
    """
    One of drone's git doors, asked in machine mode, with its verdict honoured.

    THE SPLIT, and it is the whole design of this function. A document that
    says `ok: false` is an ANSWER — drone reached git, git had something to
    say, and the caller asked for something that is not there. That is a 400
    carrying their sentence. Output that is not one JSON object is a different
    thing entirely: nobody could tell, and that is a 503. The precedent is this
    branch's own @memory config lane, which draws the same line.

    Args:
        command: The argv list WITHOUT the machine flag — it is added here so
            no lane can forget it.
        root: The branch directory.
        lane: The lane's own name, for the messages.

    Returns:
        The document, already known to carry a true verdict.

    Raises:
        ReadRefused: The door answered and said no.
        ReadUnavailable: The door could not be run, did not finish, or did not
            answer with one JSON object — which is the shape drone's own
            caller-verification refusal takes, since that one never reaches the
            door at all and puts its sentence on stderr instead.
    """
    remembered = host_refusals.remembered_refusal(root, lane)

    if remembered is not None:
        # Silent on purpose: the FIRST refusal logged this sentence, and the
        # only thing repeating it would add is the noise this exists to stop.
        raise ReadUnavailable(remembered)

    result = _ran(list(command) + [JSON_FLAG], root, lane)

    try:
        document = _parsed(result, lane)
    except ReadUnavailable as e:
        # No document at all: this root could not be READ, which is a fact
        # about the root and stays true for the next poll five seconds from
        # now. A refusing DOCUMENT is not remembered — see below.
        host_refusals.remember_refusal(root, lane, str(e))
        raise

    if not document.get(OK_KEY):
        # D0: their sentence, verbatim. This server owns the pipe, never the
        # meaning, and a refusal is the half of the meaning most worth keeping.
        #
        # NOT remembered, and the distinction is load-bearing: `ok: false` means
        # drone REACHED git and git answered — a live fact about a working
        # repository that changes with the next edit. Caching it would tell a
        # phone the tree is still broken for a minute after the operator fixed
        # it. Only a no-document failure describes the ROOT rather than its
        # contents.
        raise ReadRefused(_sentence(document, lane))

    return document


def _parsed(result: Any, lane: str) -> Dict[str, Any]:
    """
    The one JSON object a machine door answers with, or an honest could-not-tell.

    Args:
        result: The completed process.
        lane: The lane's own name.

    Returns:
        The document.

    Raises:
        ReadUnavailable: There was no document. drone's OWN sentence travels
            when it left one on stderr — which is exactly the foreign-project
            case, where the caller-verification check refuses before the door
            runs and prints its reason there. An empty change list invented
            here would paint such a branch as clean when nothing was measured.
    """
    stderr = (result.stderr or "").strip()

    try:
        document = json.loads(result.stdout or "")
    except ValueError:
        logger.warning("[host_api] the %s lane got no document (exit %s): %s", lane, result.returncode, stderr)
        reason = stderr or "no document and no reason given"
        raise ReadUnavailable(f"The {lane} lane could not tell: {reason}") from None

    if not isinstance(document, dict):
        logger.warning("[host_api] the %s lane got a %s, not a document", lane, type(document).__name__)
        raise ReadUnavailable(f"The {lane} lane answered with a {type(document).__name__}, not one JSON object")

    return document


def _sentence(document: Dict[str, Any], lane: str) -> str:
    """
    A refusal document's own words, never reworded here.

    Args:
        document: The refusing document.
        lane: The lane's own name, for the one case where there are no words.

    Returns:
        Their message, or a plain statement that they gave none. Inventing a
        reason would be this server deciding a meaning that is not its to
        decide; saying they gave none is a fact.
    """
    message = str(document.get(MESSAGE_KEY) or "").strip()

    return message or f"The {lane} lane refused without saying why"


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

    if ref:
        # A commit comes through the machine door, so a bad revision is a
        # REFUSAL in git's own words rather than a 503 — the caller named
        # something that is not there, and that is their answer to have.
        # The header belongs to the commit lane: a renderer handed it would
        # paint a phantom first file named after the word 'commit'.
        diff = _patch_of(str(_document(["drone", "@git", "show", ref], root, "commit").get(CONTENT_KEY) or ""))
    else:
        # MEASURED SHUT, 2026-08-18: the diff door has no --json. There is no
        # document to read a verdict from, so this half still reads the exit
        # code — and says so rather than pretending the two halves are alike.
        result = _ran(_patch_command(staged=staged, grain=grain), root, "diff")

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.warning("[host_api] diff returned %s for %s: %s", result.returncode, branch, stderr)
            raise ReadUnavailable(f"Diff failed: {stderr or 'no detail'}")

        diff = result.stdout or ""

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


def _patch_command(staged: bool, grain: str) -> Any:
    """
    The drone command for a working-tree patch — only the flags its door has.

    Args:
        staged: Whether the staged patch was asked for.
        grain: Which scope, already checked.

    Returns:
        The argv list to run.

    Note:
        A commit is NOT built here. It goes through the machine door with the
        rest of them, and keeping one command builder that sometimes returned
        a machine command and sometimes a rendered one would hide exactly the
        distinction this file now turns on.
    """
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

    GIT IS DRONE-ONLY, servers included. This shells `drone @git status
    --json`, the same door /v1/diff uses, and reads the document it answers
    with. THE FLAG ARRIVED AND IT FIXED A BUG, 2026-08-18: this lane used to
    read drone's rendered lines, which right-align the porcelain code into two
    columns for the screen, so every index-only change reached the phone
    dressed as a worktree one. Rows have carried git's codes verbatim since
    they existed — the contract was right all along; the data was not, and now
    is. Each row also carries `index` and `worktree` split out, because that is
    the fact the face's chips are actually built from.

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

    document = _document(command, root, "git status")

    # At repo grain the paths already ARE repo-relative, so there is no prefix
    # to strip — stripping one would eat the very part that distinguishes one
    # branch's file from another's, which is all the app is there to show.
    files, untracked, rows = _changed_files(document, root if grain == GRAIN_BRANCH else None)

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


def _changed_files(document: Dict[str, Any], root: Optional[Path]) -> Any:
    """
    Split the status document into the card's file list and a spare count.

    Args:
        document: The `drone @git status --json` document, already verified.
        root: The branch directory, used to make repo-relative paths local —
            or None at repo grain, where those names ARE the answer.

    Returns:
        (files, untracked, rows) — tracked paths that differ from HEAD named
        relative to the branch, how many untracked ones were set aside, and
        EVERY changed path with git's own two-column code beside it, plus that
        code split into the columns it is made of.

        `rows` is additive and `files` is untouched by it: @baud's desktop
        consumer parses the older pair, and untracked names appearing in the
        tracked list is exactly the disagreement this lane exists to avoid.
        The code travels VERBATIM AND UNSTRIPPED — the two columns are index
        then worktree, so 'A ' (staged new) and ' M' (modified, unstaged) are
        different answers that collapse into one letter the moment either is
        trimmed. Which code means which chip is THEIR decision, made once in
        their buildRows; a letter invented here would be a second vocabulary
        for a fact git has already stated.

    Note:
        `index` and `worktree` come from the document, and fall back to the two
        halves of the verbatim code when they do not. That fallback is not a
        guess: those columns ARE the code, by porcelain's definition, so
        deriving them is restating the same fact rather than inventing a
        second one — and it keeps this lane honest against an older drone.
    """
    prefix = _repo_relative_prefix(root) if root is not None else ""
    files = []
    rows = []
    untracked = 0

    for entry in document.get(FILES_KEY) or []:
        # UNSTRIPPED: the two columns are the answer, not noise around it.
        code = str(entry.get(STATUS_KEY) or "")
        path = str(entry.get(PATH_KEY) or "").strip()

        if not code.strip() or not path:
            continue

        if code.strip() == IGNORED_CODE:
            # Ignored is not a change. It is in no list, old or new.
            continue

        # A rename names two paths. The card shows the name the file has NOW:
        # passing the arrow through would put ' -> ' inside a filename, and a
        # phone tapping the row would ask for a file that cannot exist.
        if RENAME_ARROW in path:
            path = path.split(RENAME_ARROW)[-1].strip()

        rows.append(
            {
                "path": _branch_local(path, prefix),
                "status": code,
                "index": str(entry.get(INDEX_KEY, code[:1])),
                "worktree": str(entry.get(WORKTREE_KEY, code[1:2])),
            }
        )

        if code.strip() == UNTRACKED_CODE:
            untracked += 1
            continue

        files.append(rows[-1]["path"])

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

    MEASURED GAP, still open on 2026-08-18: the door is --oneline underneath, so
    a row carries an object name and a subject and NOTHING else — the --json
    document has exactly the two fields the rendered line had. No author, no
    date, however much a design asks for them: those live in the commit door,
    one commit at a time, and fifty subprocesses each dragging a whole patch is
    not a list lane. Asked of @drone; until then this ships what exists.

    THE CAP IS THIS LANE'S, not theirs. Measured 2026-08-18: their door does not
    clamp — asked for 99999 it answered with 1626, every commit in the
    repository. So the refusal below is the only thing standing between a phone
    and a whole history, and it refuses rather than clamps for the reason it
    always did: a clamp lets a caller believe 50 was all there was.

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
    document = _document(["drone", "@git", "log", str(limit)], root, "log")
    commits = _commits_of(document)

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
        ReadRefused: Unknown branch, a ref outside a revision's vocabulary, or a
            revision that is not in this repository — that last one is git's own
            sentence, travelling verbatim out of the refusal document.
        ReadUnavailable: drone could not be run, timed out, or answered with
            something that was not a document at all.
    """
    ref = _checked_ref(ref)
    root = resolve_branch_root(branch, project)

    # MEASURED, 2026-08-18: this door's --json is an ENVELOPE, not a structured
    # commit. Its `content` is git show's own text — header, then patch — so
    # the parsing below stays exactly as it was and only the FAILURE detection
    # moved. Saying so here is cheaper than a later reader assuming the flag
    # bought more than it did.
    shown = str(_document(["drone", "@git", "show", ref], root, "commit").get(CONTENT_KEY) or "")
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


def _commits_of(document: Dict[str, Any]) -> Any:
    """
    The commits in a log document: an object name and a subject, in order.

    Args:
        document: The `drone @git log --json` document, already verified.

    Returns:
        A list of {sha, subject}, newest first because that is the order given.

    Note:
        A row qualifies by CARRYING AN OBJECT NAME, and nothing else is asked
        of it. The old rendered lane had to check the shape of that name to
        keep a framing sentence from becoming a phantom commit; a document has
        no framing to mistake, so the check is gone with the thing it guarded
        against. An empty subject is a real commit and travels as one — the
        rendered lane silently dropped those, which was a small lie of its own.
    """
    commits = []

    for entry in document.get(COMMITS_KEY) or []:
        sha = str(entry.get(SHA_KEY) or "").strip()

        if not sha:
            continue

        commits.append({"sha": sha, "subject": str(entry.get(SUBJECT_KEY) or "").strip()})

    return commits


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
# THE LINK CARDS
# ==============================================


def read_git_remote(branch: str, project: str = "") -> Dict[str, Any]:
    """
    The repository's remote — what the phone's link-cards are built from.

    THE DOOR ARRIVED, 2026-08-18, and this lane came home. It used to live in
    its own module for one reason: there WAS no door. No verb on drone's git
    surface, nothing on their public Python surface, and the fleet's gate
    refused both raw readers — so it read the repository's configuration as the
    INI file it is, and followed worktree pointers by hand to find it. That was
    the only lane in this package that shelled nothing, and the module existed
    to keep that boundary visible. `drone @git remote --json` retires all of
    it, including the pointer-following, because git resolves commondir itself.
    The old module is archived, not deleted, next to this one.

    THE REDACTION DID NOT GO WITH IT. drone redacts credentials on their side
    too, and this lane redacts again on ours. That is not distrust and not
    duplication for its own sake: this process is the last one a URL passes
    through before it crosses a network, and a rule enforced only by somebody
    else's code is a rule that leaves silently when their code changes. The
    pins for it assert what THIS surface emits, never what upstream sent.

    A REMOTE IS A REPOSITORY FACT, so the grain says repo and the branch names
    WHICH repository — the same vocabulary the log and commit lanes use.

    Args:
        branch: Branch name, resolved through the same two doors as every other
            read — the local citizen registry for the seat, @baud's census for
            any foreign project.
        project: Optional project name. Empty means the seat.

    Returns:
        Dict with branch, grain, remote (which one answered), url (any password
        redacted), web (a browsable form, or None) and redacted.

    Raises:
        ReadRefused: Unknown branch, a repository the door refuses to speak
            for, or a repository with no remote at all — which is not
            hypothetical, real projects in this tree have none.
        ReadUnavailable: drone could not be run, timed out, or answered with
            something that was not a document.
    """
    root = resolve_branch_root(branch, project)
    document = _document(["drone", "@git", "remote"], root, "remote")

    name, configured, upstream_redacted = _chosen_remote(document)
    url, redacted = _without_credentials(configured)

    json_handler.log_operation(
        "host_api_git_remote_read",
        # The URL itself never reaches an audit line: it is the one field here
        # that can carry a secret, and a redacted copy is still not a fact worth
        # writing to disk on every read.
        {"branch": branch, "remote": name, "redacted": redacted or upstream_redacted},
    )

    return {
        "branch": branch,
        "grain": GRAIN_REPO,
        "remote": name,
        "url": url,
        # Built from the REDACTED url on purpose. _url_parts drops userinfo
        # anyway, so the two agree — and if it ever stopped agreeing, the safe
        # one is the input that already has no secret in it.
        "web": _browsable(url),
        "redacted": redacted or upstream_redacted,
    }


def _chosen_remote(document: Dict[str, Any]) -> Any:
    """
    Which remote answers, and the URL to answer with.

    Args:
        document: The `drone @git remote --json` document, already verified.

    Returns:
        (name, url, redacted) — the remote's name, its fetch URL (falling back
        to push when a remote is push-only), and whether the door says it
        already redacted something.

    Raises:
        ReadRefused: No remote at all, or one carrying no URL to offer. Both
            are the caller learning a fact about their repository, not this
            server failing — and an empty string handed to a link-card would
            render as a link to nowhere.

    Note:
        ORIGIN WINS, and otherwise the first one answers AND IS NAMED. The
        answer always says which remote it spoke for, because a card labelled
        with the wrong remote's URL is worse than no card.
    """
    remotes = [entry for entry in (document.get(REMOTES_KEY) or []) if isinstance(entry, dict)]

    if not remotes:
        raise ReadRefused("This repository has no remote configured")

    chosen = remotes[0]
    for entry in remotes:
        if str(entry.get(NAME_KEY) or "") == DEFAULT_REMOTE:
            chosen = entry
            break

    name = str(chosen.get(NAME_KEY) or "")
    url = str(chosen.get(FETCH_KEY) or chosen.get(PUSH_KEY) or "").strip()

    if not url:
        raise ReadRefused(f"The remote {name or 'this repository has'} carries no URL")

    return name, url, bool(chosen.get(REDACTED_KEY, False))


def _without_credentials(url: str) -> Any:
    """
    The URL with any password replaced, and whether one was there.

    Args:
        url: The URL as it arrived.

    Returns:
        (url, redacted).

    Note:
        A remote may carry user:token@ — that is how a machine clones a private
        repository with no human present — and this lane's whole job is handing
        that URL to a client over a network. The user survives so an operator
        still recognises their own configuration; only the secret half is
        replaced, and the boolean is what stops the change being silent.

        A BARE USER WITH NO COLON IS NOT A CREDENTIAL. That is the standard ssh
        form, git@ on every repository anyone has ever cloned, and flagging it
        would cry wolf on the commonest remote there is — an alarm that fires
        on everything is an alarm nobody reads. drone draws the same line on
        their side, independently.
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
        url: The remote's URL.

    Returns:
        The browsable form, or None for anything that is not a web address —
        a filesystem path is a directory, not a page, and putting a scheme in
        front of one would be a link card leading somewhere that never existed.
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
        url: The remote's URL.

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
        url: The remote's URL.

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
