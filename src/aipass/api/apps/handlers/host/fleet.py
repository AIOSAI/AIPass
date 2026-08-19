# =================== AIPass ====================
# Name: fleet.py
# Description: Host API Fleet Handler — reads @baud's headless fleet snapshot
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API Fleet Handler

The phone's fleet view (FPLAN-0411 C1). This handler runs `baud --snapshot` and
returns @baud's envelope UNCHANGED.

WHY THERE IS NO FLEET LOGIC IN THIS FILE
----------------------------------------
Everything here could have been computed locally — passports plus a `tmux
list-panes` would produce a plausible fleet in twenty lines. That is exactly what
this handler refuses to do. It would be a SECOND implementation of "is this agent
alive", and on the day the two disagreed, neither the phone nor the desktop would
be believed. @baud owns that judgment; this is a pipe (design call D0).

So: no field is added, dropped or renamed, `has_room` is filtered on but never
computed, and `live_agent_sessions` is served raw rather than joined to the
branch list — matching 'baud-devpulse' to branch 'devpulse' would mean owning
their session-naming convention over here. @baud confirmed the non-join and gave
a better reason than mine: the join already exists in the envelope as
`outside_room`, which they derive by matching a pane's CWD to the branch
directory rather than by parsing session names.

THREE FIELDS, THREE DIFFERENT QUESTIONS (@baud, pinned by test)
--------------------------------------------------------------
    has_room             a session BAUD named for this branch EXISTS. Name match
                         only. An empty room is has_room true.
    outside_room         an agent is seated here, in a session BAUD did not
                         create. Null when has_room is true.
    live_agent_sessions  an INTERACTIVE claude is actually alive, decided by the
                         process table. A dispatched headless claude looks like
                         the same 'claude' in a pane, so panes alone would lie.

ALIVENESS IS `live_agent_sessions` AND ONLY THAT. A client that renders "agent is
alive" from `has_room` ships a green circle over an empty room — the exact lie
@baud's m12 badge work existed to kill. This server cannot control what a client
renders, but it never manufactures an aliveness signal of its own, so the only
field that can be read for it is the one that means it.

THE GATE, AND WHY IT IS STILL HERE
---------------------------------
This exec was held shut until 2026-08-14. The shipped m12 binary did not know the
flag, and on that build an unknown argument did not error — it fell through to
tauri and OPENED A WINDOW, so a call from here would have hung the request until
something killed it. Patrick rebuilt, ran the release binary himself, and this
branch re-verified from its own seat: exit 0, one JSON envelope, 17 branches, no
window. The gate is open.

SNAPSHOT_READY stays in the code as an operational kill switch. Closed means 503
with a reason — never a synthesised fleet. That distinction is the point of the
constant, and it outlives the hazard that introduced it.

FINDING THE BINARY
------------------
`baud` is NOT on PATH. Patrick's launcher execs the built release path directly,
so this resolves to that same file first — which is exactly the argument @baud
made when they refused to ship a second artifact for C1: one binary, one version,
nothing that can silently disagree. An installed `baud` on PATH is honoured
second, and if neither exists the error names both places it looked, because
"not found" with no location is a support ticket.

@baud's exit-code contract, implemented below verbatim:
    0  real read. `error` is null and `branches` is the truth.
    1  BAUD ran, the read failed. stdout is STILL a full valid envelope with
       `error` set to a human sentence.
    2  BAUD never ran — bad flag or missing value. stdout is ZERO BYTES.
The rule the parser leans on: non-empty stdout is always a valid full envelope,
so `error != null` is the only runtime failure branch. stderr is a mirror for
humans tailing a log and is NEVER parsed.

THE SECOND HEADLESS VERB — WHY end_room() LIVES HERE AND NOT IN THE VERB LANE
-----------------------------------------------------------------------------
`--end-room` landed 2026-08-14, so /v1/verbs/kill has a door at last. The exec
belongs in THIS module rather than verbs.py for a reason that is structural, not
tidiness: verbs.py imports no subprocess machinery at all, and a test reads its
source to prove it — the capability to invent somebody else's mechanism is
absent, not merely unused. Putting the kill exec there would have spent that
property to save an import.

So one module owns the baud binary: one resolution, one cwd rule, one timeout
policy, one parser for their envelope. The verb lane calls a published function
and still cannot run a program.

Their contract for it, honoured verbatim below:
    0  did what was asked. `error` is null.
    1  refused. stdout is STILL a whole envelope, `error` carries the sentence.
    2  never ran — usage error. stdout is ZERO BYTES.
`detail` and `error` are mutually exclusive by construction, so exactly one is
non-null and it matches the exit code.

AND THE FIELD THAT IS NOT A SUCCESS FLAG: `ended`. True means this call ended a
LIVE session. False with `error: null` means there was nothing to end — still
exit 0, because a room that is already gone is the goal state. Both are
successes and they are different facts, so this module passes the distinction
through rather than flattening it. @baud asked for exactly that, and they are
right: "ended it" and "it was already gone" are different sentences on a phone.

Functions:
    snapshot_binary()      - Locate the baud binary this host should exec
    read_snapshot()        - The fleet envelope, exactly as BAUD produced it,
                             coalesced and cached for SNAPSHOT_TTL_SECONDS
    reset_snapshot_cache() - Forget it, after a verb that changed the fleet
    read_rooms()           - The room projection of that same snapshot
    end_room()             - End one named room in one project, via --end-room
"""

import copy
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host.reads import repo_root

# Opened 2026-08-14 on Patrick's rebuild, re-verified from this branch. Kept as an
# operational kill switch: set False to refuse honestly, never to fake a fleet.
SNAPSHOT_READY = True

SNAPSHOT_BINARY = "baud"

# The path Patrick's launcher execs. Coupled to @baud's build layout on purpose —
# running a DIFFERENT file than the desktop is the failure this avoids — and it
# fails loudly rather than drifting if they ever move it.
DEFAULT_BINARY_RELATIVE = Path("projects") / "baud" / "app" / "src-tauri" / "target" / "release" / "baud"

# Generous: BAUD walks a 17-branch census off disk. Short enough that a wedged
# binary cannot park a phone request indefinitely.
SNAPSHOT_TIMEOUT_SECONDS = 30

# Shorter than the read: ending a room resolves a census entry and kills one
# session, with no 17-branch walk behind it. Its own constant rather than a
# shared one, because the two verbs have no reason to move together.
END_ROOM_TIMEOUT_SECONDS = 20

# THE SNAPSHOT IS AN EXEC, AND THE PHONE POLLS (DPLAN-0305).
#
# One `baud --snapshot` costs 60-90ms and walks a 17-branch census off disk.
# /v1/fleet and /v1/rooms are the same read — rooms is a projection of the
# fleet envelope — so a face showing both cards paid for TWO process spawns per
# refresh, and a poll loop paid for two more every cycle.
#
# 1.5s: long enough that the two cards of one refresh, and a double-tap, share
# a single exec; short enough that nobody watching the screen sees a stale
# fleet. Anything longer starts LYING about a room that just ended.
SNAPSHOT_TTL_SECONDS = 1.5

# Keyed by the project asked for ('' is the anchor, and is NOT the same key as
# the anchor's own name — they are different requests even when they agree).
_snapshot_cache: Dict[str, tuple] = {}
_snapshot_flights: Dict[str, threading.Lock] = {}
_snapshot_guard = threading.Lock()

_NOT_READY = (
    "The fleet snapshot is switched off on this host (fleet.SNAPSHOT_READY is False). "
    "No fleet is reported rather than a guessed one."
)


class FleetUnavailable(Exception):
    """The fleet could not be read. Reported honestly, never faked as empty."""


class FleetMisuse(Exception):
    """
    The binary refused the invocation itself — a usage error, and ours.

    Separate from FleetUnavailable because the two deserve different status
    codes. Unavailable says 'not right now'; this says 'this server built an
    argv that binary does not accept', which no amount of retrying improves.
    """


def snapshot_binary() -> str:
    """
    Locate the baud binary to exec.

    Returns:
        Absolute path to the built release binary, or a PATH-resolved 'baud'.

    Raises:
        FleetUnavailable: Neither location has it.
    """
    built = repo_root() / DEFAULT_BINARY_RELATIVE
    if built.is_file():
        return str(built)

    found = shutil.which(SNAPSHOT_BINARY)
    if found:
        # Legitimate, just second: the built path is what the desktop runs.
        logger.info("[host_api] baud resolved from PATH at %s (no built release found)", found)
        return found

    raise FleetUnavailable(
        f"The baud binary was not found. Looked for the built release at {built}, then for {SNAPSHOT_BINARY!r} on PATH."
    )


def reset_snapshot_cache() -> None:
    """
    Forget every cached snapshot.

    Called after a verb that CHANGES the fleet (ending a room), and by the test
    suite between cases. Public because a cache nobody can clear is a cache
    that outlives its own truth.
    """
    with _snapshot_guard:
        _snapshot_cache.clear()


def _flight_lock(key: str) -> threading.Lock:
    """
    The lock that makes one key's refresh single-flight.

    Args:
        key: The project asked for.

    Returns:
        A lock unique to that key, created on first use. Per key, not global:
        a slow anchor read must not queue a different project behind it.
    """
    with _snapshot_guard:
        return _snapshot_flights.setdefault(key, threading.Lock())


def _cached_snapshot(key: str) -> Optional[Dict[str, Any]]:
    """
    The cached envelope for one key, if it is still young enough.

    Args:
        key: The project asked for.

    Returns:
        A DEEP COPY of the envelope, or None when absent or expired.

    Note:
        The copy is the point. Handing out the cached object itself means the
        first caller who edits their answer edits everyone's for the rest of
        the TTL — silently, and only under load. Copying a 17-branch envelope
        costs microseconds against a 90ms exec.
    """
    with _snapshot_guard:
        entry = _snapshot_cache.get(key)
    if entry is None:
        return None

    stored_at, envelope = entry
    # monotonic, never wall clock: a clock step must not resurrect or expire a
    # cache entry.
    if time.monotonic() - stored_at > SNAPSHOT_TTL_SECONDS:
        return None
    return copy.deepcopy(envelope)


def read_snapshot(project: str = "") -> Dict[str, Any]:
    """
    Read the fleet snapshot from BAUD, coalesced and briefly cached.

    Fresh answers within SNAPSHOT_TTL_SECONDS are served from memory, and
    concurrent callers asking for the same project share ONE exec: the first
    arrival runs it, the rest wait on that flight and read its result. Both
    matter — the TTL kills the poll cost, the single flight kills the stampede
    a page-load of several cards makes.

    A FAILURE IS NOT CACHED. Only a good envelope is stored, so a binary that
    comes back works on the very next request instead of being refused for the
    rest of the TTL. Concurrent callers still share the failed flight, which is
    what stops ten requests each waiting out their own 30s timeout.

    Args:
        project: Optional project name. CASE-SENSITIVE — it is a key in BAUD's
            census, so it travels verbatim. Empty means the anchor project.

    Returns:
        @baud's snapshot envelope, unchanged.

    Raises:
        FleetUnavailable: The seam is gated, or BAUD could not produce a read.
    """
    cached = _cached_snapshot(project)
    if cached is not None:
        return cached

    with _flight_lock(project):
        # Asked again INSIDE the lock: whoever we queued behind has just filled
        # it, and re-running the exec they already ran is the stampede itself.
        cached = _cached_snapshot(project)
        if cached is not None:
            return cached

        envelope = _read_snapshot_uncached(project)
        with _snapshot_guard:
            _snapshot_cache[project] = (time.monotonic(), copy.deepcopy(envelope))
        return envelope


def _read_snapshot_uncached(project: str = "") -> Dict[str, Any]:
    """
    Exec BAUD and return its envelope. The real read, every time.

    Args:
        project: Project name, verbatim. Empty means the anchor.

    Returns:
        @baud's snapshot envelope, unchanged.

    Raises:
        FleetUnavailable: The seam is gated, or BAUD could not produce a read.
    """
    if not SNAPSHOT_READY:
        # Checked before exec, not after. The whole point is not to run it.
        logger.info("[host_api] fleet snapshot requested while the exec is gated")
        raise FleetUnavailable(_NOT_READY)

    command = [snapshot_binary(), "--snapshot"]
    if project:
        command += ["--project", project]

    # cwd matters more than it looks: BAUD locates the root by walking UP from
    # its working directory. A server started from / or a systemd unit would fail
    # to find a root even with a valid --project, so we launch it from ours.
    root = repo_root()

    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] %s is not on PATH: %s", SNAPSHOT_BINARY, e)
        raise FleetUnavailable(f"{SNAPSHOT_BINARY} is not available on PATH — the fleet lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] fleet snapshot timed out after %ss", SNAPSHOT_TIMEOUT_SECONDS)
        raise FleetUnavailable(f"Fleet snapshot timed out after {SNAPSHOT_TIMEOUT_SECONDS}s") from e

    stdout = result.stdout or ""

    if not stdout.strip():
        # Exit 2 territory: BAUD never ran. That is a bad invocation on our side,
        # and the message says so rather than implying the caller got it wrong.
        stderr = (result.stderr or "").strip()
        logger.error(
            "[host_api] fleet invocation rejected by %s (exit %s): %s",
            SNAPSHOT_BINARY,
            result.returncode,
            stderr,
        )
        raise FleetUnavailable("Fleet snapshot invocation was rejected — this is a server-side invocation fault")

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error("[host_api] fleet snapshot was not valid JSON: %s", e)
        raise FleetUnavailable(f"Fleet snapshot could not be parsed: {e}") from e

    if not isinstance(envelope, dict):
        raise FleetUnavailable("Fleet snapshot was not an object")

    error = envelope.get("error")
    if error:
        # Their sentence, not our paraphrase, and not stderr.
        logger.warning("[host_api] fleet snapshot reported a read failure: %s", error)
        raise FleetUnavailable(str(error))

    branches = envelope.get("branches") or []
    json_handler.log_operation(
        "host_api_fleet_read",
        {"project": envelope.get("project"), "branches": len(branches), "requested": project or "anchor"},
    )

    return envelope


def list_projects() -> Dict[str, Any]:
    """
    Read BAUD's project census — the rows a switcher menu shows.

    The census is BAUD's own discovery (anchor + sealed sibling registries),
    reached the same way the snapshot is: by exec, never by re-implementing the
    discovery here where it would drift from the desktop's.

    Returns:
        @baud's census envelope, unchanged: {projects, generated_at, error}.

    Raises:
        FleetUnavailable: The seam is gated, or BAUD could not produce a census.
    """
    if not SNAPSHOT_READY:
        # Same gate as the snapshot — the census execs the same binary.
        logger.info("[host_api] project census requested while the exec is gated")
        raise FleetUnavailable(_NOT_READY)

    command = [snapshot_binary(), "--list-projects"]
    root = repo_root()

    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] %s is not on PATH: %s", SNAPSHOT_BINARY, e)
        raise FleetUnavailable(f"{SNAPSHOT_BINARY} is not available on PATH — the census routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] project census timed out after %ss", SNAPSHOT_TIMEOUT_SECONDS)
        raise FleetUnavailable(f"Project census timed out after {SNAPSHOT_TIMEOUT_SECONDS}s") from e

    stdout = result.stdout or ""

    if not stdout.strip():
        # An old binary that predates --list-projects lands here (exit 2,
        # empty stdout). The sentence names the likely fix rather than
        # implying the caller got it wrong.
        stderr = (result.stderr or "").strip()
        logger.error(
            "[host_api] census invocation rejected by %s (exit %s): %s",
            SNAPSHOT_BINARY,
            result.returncode,
            stderr,
        )
        raise FleetUnavailable(
            "Project census invocation was rejected — the baud binary may predate --list-projects; rebuild the release"
        )

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error("[host_api] project census was not valid JSON: %s", e)
        raise FleetUnavailable(f"Project census could not be parsed: {e}") from e

    if not isinstance(envelope, dict):
        raise FleetUnavailable("Project census was not an object")

    error = envelope.get("error")
    if error:
        # Their sentence, not our paraphrase.
        logger.warning("[host_api] project census reported a failure: %s", error)
        raise FleetUnavailable(str(error))

    projects = envelope.get("projects") or []
    json_handler.log_operation("host_api_project_census", {"projects": len(projects)})

    return envelope


def read_roster() -> Dict[str, Any]:
    """
    Read BAUD's cross-project roster — every working agent, everywhere.

    A snapshot is SEATED: one project per read. The phone's live and dispatched
    wheels span all projects, so this is the question /v1/fleet structurally
    cannot answer. BAUD's agent_roster() already sweeps every project in one
    /proc pass and one tmux round-trip, so it is reached by exec like everything
    else here — a second sweep implemented in Python would be a second answer.

    Returns:
        @baud's roster envelope unchanged: {branches, generated_at, error}. The
        rows are byte-identical in shape to a snapshot's, so neither side grows
        a type. `branches` may be legitimately EMPTY — nobody working anywhere
        is a true answer, and turning it into an error would make the quietest
        state of the system look like a broken lane.

    Raises:
        FleetUnavailable: The seam is gated, or BAUD ran and could not answer.
        FleetMisuse: The binary refused the invocation (exit 2, empty stdout).

    Note:
        The verb takes NO arguments — `baud --roster --project X` exits 2 with
        stdout empty and 'unknown argument' on stderr, verified against the
        release build. So an empty stdout here means this server assembled an
        argv that binary does not accept, which is why it is FleetMisuse and
        not FleetUnavailable. A release predating --roster lands in the same
        branch; its stderr is carried through so the two are told apart by
        reading the sentence rather than by guessing at the exit code.
    """
    if not SNAPSHOT_READY:
        # The same gate as the snapshot: it execs the same binary.
        logger.info("[host_api] roster requested while the exec is gated")
        raise FleetUnavailable(_NOT_READY)

    command = [snapshot_binary(), "--roster"]
    root = repo_root()

    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=SNAPSHOT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] %s is not on PATH: %s", SNAPSHOT_BINARY, e)
        raise FleetUnavailable(f"{SNAPSHOT_BINARY} is not available on PATH — the roster routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] roster sweep timed out after %ss", SNAPSHOT_TIMEOUT_SECONDS)
        raise FleetUnavailable(f"Roster sweep timed out after {SNAPSHOT_TIMEOUT_SECONDS}s") from e

    stdout = result.stdout or ""

    if not stdout.strip():
        stderr = (result.stderr or "").strip()
        logger.error(
            "[host_api] roster invocation rejected by %s (exit %s): %s",
            SNAPSHOT_BINARY,
            result.returncode,
            stderr,
        )
        raise FleetMisuse(
            f"The roster invocation was rejected by {SNAPSHOT_BINARY} (exit {result.returncode}): "
            f"{stderr or 'no reason given'}"
        )

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error("[host_api] roster output was not valid JSON: %s", e)
        raise FleetUnavailable(f"Roster could not be parsed: {e}") from e

    if not isinstance(envelope, dict):
        raise FleetUnavailable("Roster output was not an object")

    error = envelope.get("error")
    if error:
        # Their sentence, not our paraphrase.
        logger.warning("[host_api] roster reported a failure: %s", error)
        raise FleetUnavailable(str(error))

    branches = envelope.get("branches") or []
    json_handler.log_operation("host_api_roster", {"branches": len(branches)})

    return envelope


def resolve_branch(project: str, branch: str) -> Optional[Dict[str, Any]]:
    """
    One branch's row from one project's snapshot — the attach lane's census.

    The row carries the branch's real `path` (the cwd a created room starts
    in) straight from BAUD's own discovery, so this server never composes a
    filesystem path for a project it is not seated in. An unknown PROJECT
    raises with the binary's own sentence; an unknown BRANCH in a known
    project returns None — the caller's mistake, phrased by the caller.

    Args:
        project: Census name, case-sensitive, travelling verbatim.
        branch: Branch name, with or without the leading '@'.

    Returns:
        The branch's snapshot row, or None when the project has no such branch.

    Raises:
        FleetUnavailable: The seam is gated, the binary failed, or the project
            is not in BAUD's census.
    """
    wanted = branch.strip().lstrip("@")
    envelope = read_snapshot(project)
    for row in envelope.get("branches") or []:
        if row.get("name") == wanted:
            return row
    return None


def read_rooms(project: str = "") -> Dict[str, Any]:
    """
    Project the snapshot down to rooms BAUD made.

    This answers "which branches have a BAUD room", NOT "where does this agent
    live" and NOT "who is alive". A branch seated in a foreign session has
    has_room false and is absent here; its `outside_room` still travels on the
    full card via /v1/fleet, which is where that question belongs.

    Args:
        project: Optional project name, passed through to the snapshot.

    Returns:
        Dict with project, generated_at, live_agent_sessions (raw) and
        branches_with_rooms. No aliveness field is synthesised — see the module
        docstring on the three fields.

    Raises:
        FleetUnavailable: The seam is gated, or BAUD could not produce a read.
    """
    snapshot = read_snapshot(project)

    branches = snapshot.get("branches") or []
    with_rooms = [branch for branch in branches if branch.get("has_room")]

    return {
        "project": snapshot.get("project"),
        "generated_at": snapshot.get("generated_at"),
        # Raw. Joining these to the branch list would mean implementing BAUD's
        # session-naming convention here. The client joins them.
        "live_agent_sessions": snapshot.get("live_agent_sessions") or [],
        "branches_with_rooms": with_rooms,
    }


def _run_headless(args: list, timeout: int, what: str) -> Dict[str, Any]:
    """
    Run one headless baud verb and return its envelope.

    Every room verb shares an exit-code contract, so they share a parser. Three
    hand-written copies of it would drift, and the field that drifts first is
    always the empty-stdout branch — the one that decides whether "BAUD never
    ran" reads as a failure or as a quietly successful nothing.

    Args:
        args: Flag and values, WITHOUT the binary — this resolves that.
        timeout: Seconds to allow.
        what: Human name of the verb, for log lines and error sentences.

    Returns:
        @baud's envelope as a dict, whatever the exit code was on 0 or 1.

    Raises:
        FleetUnavailable: Binary missing, wedged, or the invocation rejected.
            All three are OURS, and none of them ran the verb.
    """
    command = [snapshot_binary()] + list(args)

    # Same cwd rule as the snapshot: BAUD finds its root by walking UP from the
    # working directory, so a server started from / would fail to resolve one
    # even with a valid --project.
    root = repo_root()

    try:
        result = subprocess.run(
            command,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        logger.error("[host_api] %s is not available for a %s: %s", SNAPSHOT_BINARY, what, e)
        raise FleetUnavailable(f"{SNAPSHOT_BINARY} is not available — the {what} lane routes through it") from e
    except subprocess.TimeoutExpired as e:
        logger.error("[host_api] %s timed out after %ss", what, timeout)
        raise FleetUnavailable(f"{what.capitalize()} timed out after {timeout}s") from e

    stdout = result.stdout or ""

    if not stdout.strip():
        # Exit 2: BAUD never ran, so the verb did not happen. A usage error at
        # this seam is OUR invocation being wrong, and the message says so
        # rather than implying the phone sent something bad.
        stderr = (result.stderr or "").strip()
        logger.error("[host_api] %s invocation rejected (exit %s): %s", what, result.returncode, stderr)
        raise FleetUnavailable(f"{what.capitalize()} invocation was rejected — this is a server-side invocation fault")

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as e:
        logger.error("[host_api] %s envelope was not valid JSON: %s", what, e)
        raise FleetUnavailable(f"{what.capitalize()} result could not be parsed: {e}") from e

    if not isinstance(envelope, dict):
        raise FleetUnavailable(f"{what.capitalize()} result was not an object")

    return envelope


def end_room(branch: str, project: str) -> Dict[str, Any]:
    """
    End one named room in one named project, through @baud's headless door.

    The ONE door that ends a session (Patrick, 2026-08-10). @baud proved the
    single-mechanism claim rather than asking to be trusted on it: the flag and
    the desktop button both reach the same kill, with the resolved project as an
    argument to the shared half, so the headless path cannot reach a different
    one.

    Args:
        branch: Branch whose room to end. A NAME, never a path — @baud's door
            refuses anything with a separator in it, and says so itself.
        project: Project the room belongs to. Sent VERBATIM: it is a key in
            BAUD's census, and normalising another branch's key here is how a
            working name turns into "no project named that".

    Returns:
        @baud's envelope, unchanged: project, branch, room, ended, detail,
        error, generated_at. `error` non-null means they ran and refused.
        `ended` is a fact, not a success flag — see the module docstring.

    Raises:
        FleetUnavailable: The binary is missing, wedged, or rejected the
            invocation. All three are OURS, never the caller's.
    """
    command = ["--end-room", branch]
    if project:
        command += ["--project", project]

    envelope = _run_headless(command, END_ROOM_TIMEOUT_SECONDS, "room kill")

    # The fleet just CHANGED. Serving the pre-kill snapshot for another second
    # would show the operator the room they just ended, still standing.
    reset_snapshot_cache()

    json_handler.log_operation(
        "host_api_room_kill",
        {
            "branch": branch,
            "project": project,
            "room": envelope.get("room"),
            "ended": bool(envelope.get("ended")),
            "refused": bool(envelope.get("error")),
        },
    )

    return envelope
