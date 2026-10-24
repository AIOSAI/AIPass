# =================== AIPass ====================
# Name: git_reads.py
# Description: Host API Git Read Handler — the patch, the change list, the log, one commit
# Version: 1.2.1
# Created: 2026-08-17
# Modified: 2026-10-24
# =============================================

"""
Host API Git Read Handler

Reference: docs/git_surface.md, docs/git_remote.md
"""

import json
import subprocess
import threading
from pathlib import Path
from typing import IO, Any, Dict, Optional, cast

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import refusals as host_refusals
from aipass.api.apps.handlers.host.read_cache import ReadCache

# One direction only: reads.py must never import this module.
from aipass.api.apps.handlers.host.reads import (
    GRAIN_BRANCH,
    GRAIN_REPO,
    GRAINS,
    ReadRefused,
    ReadUnavailable,
    published_root_of,
    repo_root,
    repository_of,
    resolve_branch_root,
)

MAX_DIFF_BYTES = 512 * 1024

DIFF_TIMEOUT_SECONDS = 30

# The phone asks once per branch card, all at once: uncached, N execs crossed
# the 30s timeout together. A longer timeout is not the cure.
GIT_CHANGES_TTL_SECONDS = 1.5

# Keyed by (branch, project, grain): a branch name is not unique across projects.
_changes = ReadCache("git_changes", GIT_CHANGES_TTL_SECONDS)

JSON_FLAG = "--json"

OK_KEY = "ok"
MESSAGE_KEY = "message"

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

NAME_KEY = "name"
FETCH_KEY = "fetch"
PUSH_KEY = "push"
REDACTED_KEY = "redacted"
DEFAULT_REMOTE = "origin"

# Every other code is a tracked change: what @baud's card counts via `git diff HEAD`.
UNTRACKED_CODE = "??"
IGNORED_CODE = "!!"

RENAME_ARROW = " -> "

ALL_FLAG = "--all"

FILE_HEADER = "diff --git "
# Join once per file block: a block grown by += per line is quadratic.
_BLOCK_JOIN = "".join
OLD_FILE_MARKER = "--- "
NEW_FILE_MARKER = "+++ "
HUNK_MARKER = "@@"
DEV_NULL = "/dev/null"
OLD_PREFIX = "a/"
NEW_PREFIX = "b/"

COMMIT_HEADER = "commit "
AUTHOR_HEADER = "Author: "
DATE_HEADER = "Date:"
MESSAGE_INDENT = "    "
COMMIT_LABELS = ((COMMIT_HEADER, "sha"), (AUTHOR_HEADER, "author"), (DATE_HEADER, "date"))


MAX_LOG_COMMITS = 50
DEFAULT_LOG_COMMITS = 20

# A leading dash is refused separately: mid-name it is a character, in front an option.
SAFE_REF_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/~^@{}-")
MAX_REF_LENGTH = 200

SCHEME_SEPARATOR = "://"
BROWSABLE_SCHEMES = ("http", "https")
SSH_SCHEMES = ("ssh", "git", "git+ssh")
WEB_SCHEME = "https"
CLONE_SUFFIX = ".git"
REDACTION = "***"


def _ran(command: Any, root: Path, lane: str) -> Any:
    """Run one of drone's doors, or fail in words naming which lane could not."""
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
        raise _timed_out(root, lane) from e


def _timed_out(root: Path, lane: str) -> ReadUnavailable:
    """The refusal for a door that outran its timeout."""
    # The root goes in the log only: the sentence travels to a handset, no host paths.
    logger.error("[host_api] the %s lane timed out after %ss reading %s", lane, DIFF_TIMEOUT_SECONDS, root)
    return ReadUnavailable(f"The {lane} lane timed out after {DIFF_TIMEOUT_SECONDS}s")


def _streamed(command: Any, root: Path, lane: str) -> Any:
    """
    Run a door whose stdout is the patch, reading no more than MAX_DIFF_BYTES + 1 of it.

    Past the cap the door is killed: its exit code is then ours, not a verdict.
    """
    try:
        child = subprocess.Popen(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as e:
        logger.error("[host_api] drone not found for the %s lane: %s", lane, e)
        raise ReadUnavailable(f"drone is not available on PATH — the {lane} lane routes through it") from e

    expired = threading.Event()
    timer = threading.Timer(DIFF_TIMEOUT_SECONDS, lambda: (expired.set(), child.kill()))
    timer.start()
    out_pipe, err_pipe = cast(IO[bytes], child.stdout), cast(IO[bytes], child.stderr)

    try:
        stdout = out_pipe.read(MAX_DIFF_BYTES + 1)
        cut = len(stdout) > MAX_DIFF_BYTES
        if cut:
            child.kill()
        stderr = err_pipe.read().decode("utf-8", errors="replace")
        returncode = child.wait()
    finally:
        timer.cancel()
        out_pipe.close()
        err_pipe.close()

    if expired.is_set():
        raise _timed_out(root, lane)

    return stdout.decode("utf-8", errors="ignore"), stderr, returncode, cut


def _document(command: Any, root: Path, lane: str) -> Dict[str, Any]:
    """One of drone's git doors, asked in machine mode, with its verdict honoured."""
    remembered = host_refusals.remembered_refusal(root, lane)

    if remembered is not None:
        raise ReadUnavailable(remembered)

    result = _ran(list(command) + [JSON_FLAG], root, lane)

    try:
        document = _parsed(result, lane)
    except ReadUnavailable as e:
        # No document is a fact about the root, so it is remembered across polls.
        host_refusals.remember_refusal(root, lane, str(e))
        raise

    if not document.get(OK_KEY):
        # Not remembered: `ok: false` is live and caching it reports a fixed tree as broken.
        raise ReadRefused(_sentence(document, lane))

    return document


def _parsed(result: Any, lane: str) -> Dict[str, Any]:
    """The one JSON object a machine door answers with, or an honest could-not-tell."""
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
    """A refusal document's own words, never reworded here."""
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

    A `path` the worktree patch lacks is asked of the index before it is
    refused, so an index-only row opens; `staged` says which half was served.
    """
    if ref:
        ref = _checked_ref(ref)

        if grain and grain != GRAIN_REPO:
            raise ReadRefused(f"A commit is repo-wide by construction — {grain!r} grain cannot be asked of {ref}")
        if staged:
            raise ReadRefused(f"A commit has no staging area — staged cannot be asked of {ref}")

        grain = GRAIN_REPO
    else:
        grain = _checked_grain(grain)

    root = resolve_branch_root(branch, project)

    if ref:
        # The commit header is stripped: a renderer would paint it as a phantom first file.
        diff = _patch_of(str(_document(["drone", "@git", "show", ref], root, "commit").get(CONTENT_KEY) or ""))
        cut = False
    else:
        diff, cut = _working_patch(root, branch, staged, grain)

    if path:
        prefix = _repo_relative_prefix(root) if grain == GRAIN_BRANCH else ""
        wanted = path if path.startswith(prefix) else prefix + path
        block = _one_files_patch(_whole_blocks(diff, cut), wanted)
        if block is None and not cut and not ref and not staged:
            diff, cut = _working_patch(root, branch, True, grain)
            staged, block = True, _one_files_patch(_whole_blocks(diff, cut), wanted)
        if block is None and cut:
            raise ReadRefused(f"This patch is over the {MAX_DIFF_BYTES} byte cap, so {path} could not be read whole")
        if block is None:
            raise ReadRefused(f"No changes to {path} in this patch")
        diff, cut = block, False

    raw_bytes = len(diff.encode("utf-8"))
    truncated = False

    if raw_bytes > MAX_DIFF_BYTES or cut:
        if path:
            raise ReadRefused(f"{path} is {raw_bytes} bytes of patch, over the {MAX_DIFF_BYTES} byte cap")

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


def _working_patch(root: Path, branch: str, staged: bool, grain: str) -> Any:
    """
    A working-tree patch, and whether it was cut at the cap.

    The diff door has no --json, so its exit code is the verdict.
    """
    stdout, stderr, returncode, cut = _streamed(_patch_command(staged=staged, grain=grain), root, "diff")

    if returncode != 0 and not cut:
        stderr = stderr.strip()
        logger.warning("[host_api] diff returned %s for %s: %s", returncode, branch, stderr)
        raise ReadUnavailable(f"Diff failed: {stderr or 'no detail'}")

    return stdout, cut


def _whole_blocks(patch: str, cut: bool) -> str:
    """A patch without its last file block when the cap may have severed it."""
    if not cut:
        return patch

    return patch[: patch.rfind("\n" + FILE_HEADER) + 1]


def _patch_command(staged: bool, grain: str) -> Any:
    """The drone command for a working-tree patch — only the flags its door has."""
    command = ["drone", "@git", "diff"]

    if staged:
        command.append("--staged")

    if grain == GRAIN_REPO:
        command.append(ALL_FLAG)

    return command


def read_git_changes(branch: str, project: str = "", grain: str = "") -> Dict[str, Any]:
    """A branch's change list, coalesced and briefly cached."""
    # Normalised before it becomes a key, so two spellings share one exec.
    grain = _checked_grain(grain)
    return _changes.get(
        (branch, project, grain),
        lambda: _read_git_changes_uncached(branch, project, grain),
    )


def _read_git_changes_uncached(branch: str, project: str = "", grain: str = "") -> Dict[str, Any]:
    """A branch's uncommitted change list — @baud's desktop card contract, served."""
    grain = _checked_grain(grain)
    root = resolve_branch_root(branch, project)

    command = ["drone", "@git", "status"]
    if grain == GRAIN_REPO:
        command.append(ALL_FLAG)

    document = _document(command, root, "git status")

    files, untracked, rows = _changed_files(document, root if grain == GRAIN_BRANCH else None)

    json_handler.log_operation(
        "host_api_git_changes_read",
        {"branch": branch, "grain": grain, "count": len(files), "untracked": untracked},
    )

    answer = {
        "branch": branch,
        "grain": grain,
        "files": files,
        "count": len(files),
        "untracked": untracked,
        "rows": rows,
    }
    if grain == GRAIN_REPO:
        # The files root repo-relative paths open under; branch grain's are branch-relative.
        repository = repository_of(root.resolve())
        answer["root"] = published_root_of(repository) if repository is not None else None

    return answer


def _changed_files(document: Dict[str, Any], root: Optional[Path]) -> Any:
    """Split the status document into the card's file list and a spare count."""
    prefix = _repo_relative_prefix(root) if root is not None else ""
    files = []
    rows = []
    untracked = 0

    for entry in document.get(FILES_KEY) or []:
        # Unstripped: 'A ' (staged) and ' M' (unstaged) collapse once trimmed.
        code = str(entry.get(STATUS_KEY) or "")
        path = str(entry.get(PATH_KEY) or "").strip()

        if not code.strip() or not path:
            continue

        if code.strip() == IGNORED_CODE:
            continue

        # A rename shows the name the file has now; a tap must ask for a real file.
        if RENAME_ARROW in path:
            path = path.split(RENAME_ARROW)[-1].strip()

        rows.append(
            {
                "path": _branch_local(path, prefix),
                "status": code,
                # Fallback for an older drone: by porcelain's definition the columns are the code.
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

    Discovery first, the seat only as fallback: a foreign project sits outside
    the seat and a nested repository (projects/baud) inside it.
    """
    resolved = root.resolve()

    for base in (repository_of(resolved), repo_root()):
        prefix = _prefix_under(resolved, base)
        if prefix is not None:
            return prefix

    # Logged: for a seated branch, un-prefixed rows would be the only symptom of a moved seat.
    logger.info("[host_api] no repository root above %s — paths stay as drone printed them", root)
    return ""


def _prefix_under(path: Path, base: Optional[Path]) -> Optional[str]:
    """How to spell `path` relative to `base`, or None when it does not sit there."""
    if base is None:
        return None

    resolved_base = base.resolve()
    if not path.is_relative_to(resolved_base):
        return None

    return path.relative_to(resolved_base).as_posix() + "/"


def _branch_local(path: str, prefix: str) -> str:
    """One repo-relative path, made local to the branch like --relative does."""
    if prefix and path.startswith(prefix):
        return path[len(prefix) :]
    return path


def read_git_log(branch: str, project: str = "", limit: int = DEFAULT_LOG_COMMITS) -> Dict[str, Any]:
    """The repository's recent commits — a short object name and a subject."""
    if limit < 1 or limit > MAX_LOG_COMMITS:
        # drone's log door does not clamp; refused, not clamped, so 50 never reads as all.
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
    """One commit's facts and its per-file stat list — never its patch."""
    ref = _checked_ref(ref)
    root = resolve_branch_root(branch, project)

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
    """Which scope was asked for, or a refusal naming both."""
    if not grain:
        return GRAIN_BRANCH

    if grain not in GRAINS:
        raise ReadRefused(f"Unknown grain {grain!r} — this lane serves {GRAIN_BRANCH} or {GRAIN_REPO}")

    return grain


def _checked_ref(ref: str) -> str:
    """A revision, or a refusal — decided before any subprocess exists."""
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
    """The patch inside a shown commit, without the header lines that frame it."""
    lines = shown.splitlines(keepends=True)

    for index, line in enumerate(lines):
        if line.startswith(FILE_HEADER):
            return "".join(lines[index:])

    return ""


def _per_file_blocks(patch: str) -> Any:
    """Split a patch into one block per file, keyed on the per-file header."""
    blocks: Any = []

    for line in patch.splitlines(keepends=True):
        if line.startswith(FILE_HEADER):
            blocks.append([line])
        elif blocks:
            blocks[-1].append(line)

    return [_BLOCK_JOIN(block) for block in blocks]


def _one_files_patch(patch: str, path: str) -> Optional[str]:
    """One file's block out of a patch, or None when the patch does not touch it."""
    for block in _per_file_blocks(patch):
        # Exact: a substring match would answer for other_hello.txt.
        if _path_of_block(block) == path:
            return block

    return None


def _path_of_block(block: str) -> str:
    """
    Which file a block is about, read from the lines that name exactly one.

    The first naming line wins: a hunk line '-- x' removed reads '--- x', but
    the block's own headers always come before its first hunk.
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

    The two halves must agree, so a filename containing ' b/' cannot split it wrong.
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

    The '---'/'+++' header lines would otherwise count as a phantom +1/-1 per file.
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

    An empty subject is a real commit and travels as one.
    """
    commits = []

    for entry in document.get(COMMITS_KEY) or []:
        sha = str(entry.get(SHA_KEY) or "").strip()

        if not sha:
            continue

        commits.append({"sha": sha, "subject": str(entry.get(SUBJECT_KEY) or "").strip()})

    return commits


def _commit_facts(shown: str) -> Dict[str, str]:
    """A commit's header, read on its label prefixes and its display indent."""
    facts = {"sha": "", "author": "", "date": ""}
    message_lines = []

    for line in _header_lines(shown):
        key, value = _labelled(line)

        if key and not facts[key]:
            facts[key] = value
        elif line.startswith(MESSAGE_INDENT):
            # Kept, the display indent would render every body as a code block.
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
    """Every line of a shown commit before its patch begins."""
    lines = []

    for line in shown.splitlines():
        if line.startswith(FILE_HEADER):
            break
        lines.append(line)

    return lines


def _labelled(line: str) -> Any:
    """Which header field a line carries, if any."""
    for prefix, key in COMMIT_LABELS:
        if line.startswith(prefix):
            return key, line[len(prefix) :].strip()

    return "", ""


def read_git_remote(branch: str, project: str = "") -> Dict[str, Any]:
    """The repository's remote — what the phone's link-cards are built from."""
    root = resolve_branch_root(branch, project)
    chosen = _chosen_remote(_document(["drone", "@git", "remote"], root, "remote"))

    if chosen is None:
        json_handler.log_operation("host_api_git_remote_read", {"branch": branch, "remote": None, "redacted": False})
        return {"branch": branch, "grain": GRAIN_REPO, "remote": None, "url": None, "web": None, "redacted": False}

    name, configured, upstream_redacted = chosen
    url, redacted = _without_credentials(configured)

    json_handler.log_operation(
        "host_api_git_remote_read",
        # The URL never reaches an audit line: it is the one field that can carry a secret.
        {"branch": branch, "remote": name, "redacted": redacted or upstream_redacted},
    )

    return {
        "branch": branch,
        "grain": GRAIN_REPO,
        "remote": name,
        "url": url,
        # From the redacted url on purpose, should _url_parts ever stop dropping userinfo.
        "web": _browsable(url),
        "redacted": redacted or upstream_redacted,
    }


def _chosen_remote(document: Dict[str, Any]) -> Any:
    """Which remote answers, and the URL to answer with."""
    remotes = [entry for entry in (document.get(REMOTES_KEY) or []) if isinstance(entry, dict)]

    if not remotes:
        return None

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
    The URL with any secret in its userinfo replaced, and whether one was there.

    A password goes and its user stays. A colonless userinfo is the secret itself
    (`https://<token>@`), except over ssh, where `git@` is only the login name.
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
    if ":" in userinfo:
        kept = userinfo.split(":", 1)[0] + ":" + REDACTION
    elif scheme in SSH_SCHEMES:
        return url, False
    else:
        kept = REDACTION

    logger.info("[host_api] a credential in a remote URL was redacted before it left this process")

    return f"{scheme}{SCHEME_SEPARATOR}{kept}@{rest[at + 1 :]}", True


def _browsable(url: str) -> Optional[str]:
    """A URL a person can open, or None when there honestly is not one."""
    scheme, host, path = _url_parts(url)

    if scheme is None:
        return None

    if scheme in BROWSABLE_SCHEMES:
        # http is not upgraded: that would decide something about a host we cannot know.
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

    Userinfo is dropped here: the one place that keeps it out of a browsable link.
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

    Trap: C:\\repos carries a colon too; both halves are checked, or a link
    card would point at a machine named C.
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
