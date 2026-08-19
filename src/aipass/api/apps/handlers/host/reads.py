# =================== AIPass ====================
# Name: reads.py
# Description: Host API Read Handler — file and directory reads behind the name fence
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-18
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

THE FENCE GAINED ROOTS — FPLAN-0443, 2026-08-18
------------------------------------------------------------------------
Patrick: "rn I can only see into agent files... I cant explore home. or project
files outside agents." The fence answered exactly one kind of word, so
agent-land was the whole of where a phone could stand. It answers four now
(ROOT_KINDS), and the widening is the ROSTER, not the rule: the client still
sends a name, the server still decides what it means, and the same containment
runs underneath all four. resolve_branch_root is the branch arm of resolve_root
and every caller of it is untouched.

Where each floor comes from stays a lookup, never a composition: the registry
for a branch, @baud's census for a project, Path.home() for home, this server's
own registry parent for aipass.

THE EXPOSURE IS ON THE RECORD (FPLAN-0443 Notes, Patrick's ruling): fully open,
no deny-list and no extra scope gate, so a read-scope token reads ~/.ssh and
friends over the tailnet. The cheap reversal is a name deny-list here plus
require_scope("operate") on the home arm; nothing in this shape forecloses it.

Caps: 512KB on both files and diffs, matching BAUD's read fence. A cap that is
hit is REPORTED, never a silent truncation.

Functions:
    resolve_root()        - Any of the four kinds of name to an absolute floor
    resolve_branch_root() - Registry lookup, branch name to absolute path
    list_roots()          - The roster of every place the file lane may stand
    read_file()           - Read one file under a root, fenced and capped
    list_dir()            - One level of one directory, fenced and capped
    seated_project()      - The project this server is seated in
    repo_root()           - The seat's repository root
    home_root()           - The operator's home directory

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

# ROOT KINDS — the whole vocabulary of the fence (FPLAN-0443).
#
# For as long as it existed the fence answered exactly ONE kind of word, a
# citizen name, which is why browsing stopped at agent-land. Patrick named the
# cost on 2026-08-18: "rn I can only see into agent files... I cant explore
# home. or project files outside agents."
#
# These four are the words it answers now, and they are a CLOSED set resolved
# server-side. A kind is not a path and no arrangement of kinds composes one —
# the client still sends a NAME, the server still decides what it means, and
# the containment below still catches a name that lies. The fence widened; it
# was never removed.
ROOT_BRANCH = "branch"
ROOT_HOME = "home"
ROOT_PROJECT = "project"
ROOT_AIPASS = "aipass"
ROOT_KINDS = (ROOT_BRANCH, ROOT_HOME, ROOT_PROJECT, ROOT_AIPASS)

# The kinds that name nothing: there is one home directory and one repository
# this server is seated in. A name alongside either is a caller error, and it
# is REFUSED rather than dropped — see resolve_root.
_NAMELESS_KINDS = (ROOT_HOME, ROOT_AIPASS)


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


def home_root() -> Path:
    """
    The operator's home directory — the root Patrick named first.

    A location primitive like repo_root(), and deliberately as plain: whether
    the directory exists is resolve_root's question, not this one's.

    Returns:
        Absolute path to the home directory.

    Raises:
        RuntimeError: The platform could not name a home directory at all.
            Left to the caller, which turns it into ReadUnavailable — a home
            that cannot be found is this machine's problem, never the phone's.
    """
    return Path.home().resolve()


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

    listed = str(info.get("path", "")).strip()
    if not listed:
        # Path("") resolves to the process's CWD, which IS a real directory —
        # so a citizen registered without a path would have resolved to
        # wherever this server happens to be standing and read as that
        # branch's root. Found while widening the fence, fixed here.
        raise ReadUnavailable(f"Registry lists {branch!r} without a path")

    root = Path(listed).resolve()
    if not root.is_dir():
        raise ReadUnavailable(f"Registry lists {branch!r} at a path that does not exist: {root}")

    return root


def _project_root(name: str) -> Path:
    """
    Resolve a project name to its root, through @baud's census.

    This server never composes a filesystem path for a project — the row comes
    from BAUD's own discovery, the same engine the desktop and the attach lane
    trust, so there is one implementation of "where does this project live".

    THE MATCH IS EXACT, on purpose. The name arrives from a roster this server
    published FROM this census, so an exact comparison is a comparison against
    the census's own spelling. This module already documents three different
    project-matching rules (the seat is case-insensitive, foreign branches
    travel verbatim, the fleet lane is @baud's); a fourth invented here would
    make the file's behaviour indefensible as a whole. The refusal names where
    the right spelling comes from instead.

    Args:
        name: Census name, exactly as /v1/roots published it.

    Returns:
        Absolute path to the project root — existence is the caller's check.

    Raises:
        ReadRefused: No name, or no project by that name in the census.
        ReadUnavailable: The census could not be produced, or lists the project
            without a path.
    """
    wanted = name.strip()
    if not wanted:
        raise ReadRefused(f"A project name is required for the {ROOT_PROJECT!r} root")

    # Imported HERE for the same cycle reason _external_branch_root documents.
    from aipass.api.apps.handlers.host import fleet as host_fleet

    try:
        census = host_fleet.list_projects()
    except host_fleet.FleetUnavailable as e:
        logger.info("[host_api] census could not be produced for root %r: %s", wanted, e)
        raise ReadUnavailable(str(e)) from e

    for row in census.get("projects") or []:
        if str(row.get("name", "")) != wanted:
            continue

        listed = str(row.get("root", "")).strip()
        if not listed:
            # Path("") resolves to the CWD, which is a real directory — a blank
            # row would otherwise serve wherever this process is standing.
            raise ReadUnavailable(f"The census lists {wanted!r} without a path")

        return Path(listed).resolve()

    raise ReadRefused(f"No project named {wanted!r} in the roster — the names come from /v1/roots")


def resolve_root(kind: str, name: str = "", project: str = "") -> Path:
    """
    Resolve one of the fence's four kinds of word to an absolute floor.

    resolve_branch_root is the BRANCH ARM of this function and keeps every
    existing caller bit-identical — there is no second implementation of
    "where does a citizen live" and no caller had to change to gain three more
    kinds of place to stand.

    A PARAMETER THAT CANNOT MEAN ANYTHING IS REFUSED, NEVER DROPPED. The kinds
    that name nothing take no name, and only the branch kind is qualified by a
    project. Silently ignoring either would let a caller believe an answer was
    scoped when it was not — the same reason /v1/roster refuses every parameter
    rather than filtering on the ones it understands.

    Args:
        kind: One of ROOT_KINDS. There is no default here on purpose: "absent
            means branch" is the READ LANE's rule, because absent is a request
            that named no root. A resolver that guessed would turn every typo
            into somebody's branch.
        name: The name within that kind — a citizen name, a census project
            name, or empty for the kinds that name nothing.
        project: Only meaningful for the branch kind, where it qualifies which
            project's branch is meant.

    Returns:
        Absolute path to the floor a read may stand on.

    Raises:
        ReadRefused: Unknown kind, a missing name, or a parameter this kind
            cannot use.
        ReadUnavailable: The floor could not be produced or is not a directory.
    """
    if kind not in ROOT_KINDS:
        raise ReadRefused(f"Unknown root kind: {kind!r}. The fence answers {', '.join(ROOT_KINDS)}")

    if kind == ROOT_BRANCH:
        return resolve_branch_root(name, project)

    # Past this line nothing resolves a branch, so a project qualifies nothing.
    if project.strip():
        raise ReadRefused(f"The {kind!r} root does not live inside a project — send no project")

    if kind in _NAMELESS_KINDS and name.strip() and name.strip() != kind:
        # THE ROOT MAY NAME ITSELF — @devpulse's ruling, 2026-08-18, after
        # @baud's picker was measured against this fence. Their browser sends
        # the first path component for EVERY root, and a kind that names
        # nothing stands in for itself rather than send an empty component
        # that composes a leading slash their own transport refuses. A word
        # equal to the kind is not a parameter that cannot mean anything: it
        # names the root, straight off the roster row this server published.
        # Any OTHER name is still refused, so the doctrine is intact —
        # nothing meaningless is dropped, nothing meaningful is refused.
        # Exact, like the project names, and for the same reason.
        raise ReadRefused(f"The {kind!r} root names nothing — send no name, or the kind itself; received {name!r}")

    if kind == ROOT_HOME:
        try:
            root = home_root()
        except RuntimeError as e:
            # A machine that cannot name a home directory is our fault to
            # report, not a request the phone got wrong.
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
    """
    Every place the file lane may stand — the roster the phone's picker renders.

    A face that hardcoded this list would be a face that lies the day a project
    is added, which is the whole reason this is a door rather than a constant.

    NO BRANCH ROWS. Agents already have their own door (the wheel resolves a
    citizen and browses it), and a branch row could not carry the project that
    qualifies it — so a roster of branches would be true only at the seat.

    ONE ROW PER FLOOR. The anchor project and the aipass root are the SAME
    directory; publishing both would be a roster that lies about how many
    places there are. The duplicate row goes, and BOTH selectors still resolve.

    A BROKEN CENSUS REFUSES THE WHOLE ROSTER rather than serving the two rows
    that need no census. Measured against the consumer rather than assumed:
    @baud's RootsScreen renders `body.roots` and ignores every other field, so
    a partial roster carrying an error nobody reads would print as "there are
    no projects". Their screen shows a refusal in our own words instead.

    Returns:
        Dict with `roots`: rows of {kind, name, label}, in the order home,
        aipass, then the census's own order.

    Raises:
        ReadUnavailable: The census could not be produced.
    """
    from aipass.api.apps.handlers.host import fleet as host_fleet

    aipass = repo_root().resolve()

    # 'home' prints the word for the place rather than the directory's own name,
    # which is a username and not what anyone calls it.
    roots: list = [
        {"kind": ROOT_HOME, "name": "", "label": "home"},
        {"kind": ROOT_AIPASS, "name": "", "label": aipass.name},
    ]

    try:
        census = host_fleet.list_projects()
    except host_fleet.FleetUnavailable as e:
        logger.info("[host_api] roots roster refused — no census: %s", e)
        raise ReadUnavailable(str(e)) from e

    dropped = []
    for row in census.get("projects") or []:
        name = str(row.get("name", "")).strip()
        listed = str(row.get("root", "")).strip()

        if not name or not listed:
            # Named, never silent: a row the fence could not be handed is a row
            # this roster must not draw, and a drop nobody logs reads as a
            # census that returned fewer projects.
            dropped.append(row)
            continue

        root = Path(listed).resolve()
        if root == aipass:
            continue

        # The label is what a person calls the place; the name is what the
        # fence will actually be handed. @baud's row prints the second under
        # the first when they differ.
        roots.append({"kind": ROOT_PROJECT, "name": name, "label": root.name or name})

    if dropped:
        logger.warning("[host_api] roots roster dropped %s census row(s) with no name or path", len(dropped))

    json_handler.log_operation("host_api_roots_roster", {"roots": len(roots), "dropped": len(dropped)})

    return {"roots": roots}


# ==============================================
# READS
# ==============================================


def read_file(branch: str, file: str, project: str = "", root: str = "") -> Dict[str, Any]:
    """
    Read one file under a named root.

    Args:
        branch: The name WITHIN the root kind — a citizen name on the branch
            lane (the default), a census project name under the project root,
            and empty for the kinds that name nothing. Resolved, never a path.
        file: Path RELATIVE to that root, e.g. "apps/api.py".
        project: Optional project name, qualifying a branch. Empty means the
            seat; any project @baud's census knows is served.
        root: Which KIND of root to stand on — see ROOT_KINDS. ABSENT MEANS
            BRANCH, which is not a default invented here: it is the only
            meaning this verb has ever had, so a caller written before roots
            existed asks for exactly what it always asked for.

    Returns:
        Dict with branch, file, bytes, truncated (always False — a cap hit is an
        error here, not a quiet trim), content, and `floor`: the absolute path
        of the root this read stood on, which the caller needs to build a path
        that pastes into a terminal. A request that NAMED a root also gets it
        echoed back.

    Raises:
        ReadRefused: Fence violation, unknown root or branch, missing file,
            over cap, or a file that is not UTF-8 text.
        ReadUnavailable: Registry, census or filesystem failure.
    """
    floor = resolve_root(root or ROOT_BRANCH, branch, project)
    target = _fence(floor, file)

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

    # The trail names the root: a home read and a branch read must not be the
    # same line in the audit, because the exposure this widening carries is on
    # the record (FPLAN-0443 Notes) and a record has to carry it.
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
        # THE FLOOR — the absolute path of the root this answer stood on
        # (@devpulse's rider, 2026-08-18). The face knows <root>/<relative> and
        # nothing about where the root sits on disk, so a copy-path button has
        # to be handed the absolute half; composing it there would mean the
        # phone holding a second opinion about where anything lives.
        "floor": str(floor),
    }
    if root:
        answer["root"] = root

    return answer


def list_dir(branch: str = "", dir: str = "", project: str = "", root: str = "") -> Dict[str, Any]:
    """
    List one directory level under a named root — the phone's file browser.

    Mirrors the desktop's `list_dir`: dirs first, then files, both
    alphabetical, noise directories filtered at the source. One level only;
    the caller descends by asking again.

    Args:
        branch: The name WITHIN the root kind — see read_file. Empty is now a
            legitimate request rather than a malformed one, because `home` and
            `aipass` name nothing.
        dir: Directory RELATIVE to that root, empty for the root itself.
        project: Optional project name, qualifying a branch.
        root: Which KIND of root to stand on. Absent means branch.

    Returns:
        Dict with branch, dir, entries (name, path relative to the root,
        is_dir), truncated — True when the level was over the cap and the tail
        was dropped — and `floor`, the absolute path of the root. `floor` plus
        an entry's path is that entry's real location on disk, which is the
        join the phone's copy-path button performs. A named root is echoed back.

    Raises:
        ReadRefused: Fence violation, unknown root or branch, or not a
            directory.
        ReadUnavailable: Registry, census or filesystem failure.
    """
    floor = resolve_root(root or ROOT_BRANCH, branch, project)
    # The fence requires a name; the root itself is the one level the caller
    # may name with nothing.
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
    truncated = len(entries) > MAX_DIR_ENTRIES
    if truncated:
        entries = entries[:MAX_DIR_ENTRIES]

    audit: Dict[str, Any] = {"branch": branch, "dir": dir or ".", "entries": len(entries), "truncated": truncated}
    if root:
        audit["root"] = root
    json_handler.log_operation("host_api_dir_list", audit)

    answer = {
        "branch": branch,
        "dir": dir,
        "entries": entries,
        "truncated": truncated,
        # The ROOT's absolute path, not the listed directory's: entry paths are
        # already relative to the root, so a floor that walked with `dir` would
        # double-count the relative part on the face's own join.
        "floor": str(floor),
    }
    if root:
        answer["root"] = root

    return answer


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
        root: Absolute, resolved floor — any of the fence's kinds. This gate
            never asks which kind it is standing on, which is why widening the
            roster did not widen the containment.
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
        raise ReadRefused("File must be relative to the root, not an absolute path")

    parts = Path(candidate).parts
    if ".." in parts:
        raise ReadRefused("File name may not contain '..'")

    resolved = (root / candidate).resolve()

    # The last line of defence: a symlink inside the branch can still point out
    # of it, and only a post-resolution check sees that.
    if resolved != root and root not in resolved.parents:
        logger.warning("[host_api] fence blocked a read outside %s: %r", root, file)
        raise ReadRefused("File resolves outside the root")

    if not resolved.exists():
        raise ReadRefused(f"No such file: {file!r}")

    return resolved
