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
their session-naming convention over here.

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

Functions:
    snapshot_binary() - Locate the baud binary this host should exec
    read_snapshot()   - The fleet envelope, exactly as BAUD produced it
    read_rooms()      - The room projection of that same snapshot
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

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

_NOT_READY = (
    "The fleet snapshot is switched off on this host (fleet.SNAPSHOT_READY is False). "
    "No fleet is reported rather than a guessed one."
)


class FleetUnavailable(Exception):
    """The fleet could not be read. Reported honestly, never faked as empty."""


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


def read_snapshot(project: str = "") -> Dict[str, Any]:
    """
    Read the fleet snapshot from BAUD.

    Args:
        project: Optional project name. CASE-SENSITIVE — it is a key in BAUD's
            census, so it travels verbatim. Empty means the anchor project.

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


def read_rooms(project: str = "") -> Dict[str, Any]:
    """
    Project the snapshot down to room information.

    Args:
        project: Optional project name, passed through to the snapshot.

    Returns:
        Dict with project, generated_at, live_agent_sessions (raw) and
        branches_with_rooms.

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
