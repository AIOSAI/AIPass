# =================== AIPass ====================
# Name: fleet.py
# Description: Host API Fleet Handler — reads @baud's headless fleet snapshot
# Version: 1.1.0
# Created: 2026-08-14
# Modified: 2026-10-17
# =============================================

"""
Host API Fleet Handler

Reference: docs/host_surfaces.md
@baud's exit contract: non-empty stdout is always a whole envelope (`error` set
on failure); empty stdout means BAUD never ran (exit 2). stderr is never parsed.
"""

import copy
import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host.reads import repo_root

# Operational kill switch: False refuses with 503, never fakes a fleet.
SNAPSHOT_READY = True

SNAPSHOT_BINARY = "baud"

HEADLESS_BINARY = "baud-cli"

INSTALLED_BINARY_RELATIVE = Path(".aipass") / "baud" / "bin" / HEADLESS_BINARY

# Coupled to @baud's build layout on purpose: the same file the owner's launcher execs.
DEFAULT_BINARY_RELATIVE = Path("projects") / "baud" / "app" / "src-tauri" / "target" / "release" / "baud"

CHECKOUT_HEADLESS_RELATIVE = DEFAULT_BINARY_RELATIVE.with_name(HEADLESS_BINARY)

SOURCE_CONFIGURED = "configured"
SOURCE_INSTALLED = "installed"
SOURCE_CHECKOUT = "checkout"
SOURCE_PATH = "path"
SOURCE_MISSING = "missing"

INSTALL_BINARY_HINT = "Install it: aipass baud install."

SNAPSHOT_TIMEOUT_SECONDS = 30

END_ROOM_TIMEOUT_SECONDS = 20

# Long enough that /v1/fleet and /v1/rooms of one refresh share an exec; any
# longer shows a room that just ended as still standing.
SNAPSHOT_TTL_SECONDS = 1.5

# '' (the anchor) is a different key from the anchor's own name, deliberately.
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

    Distinct from FleetUnavailable: no amount of retrying improves it.
    """


@dataclass(frozen=True)
class BinaryLocation:
    """Which baud binary a request would exec, and which step of the order found it."""

    path: str
    source: str
    looked: Tuple[str, ...]

    def runnable(self) -> bool:
        """Whether the path is an executable regular file right now."""
        return bool(self.path) and _is_runnable(Path(self.path))

    def problem(self) -> str:
        """Why a request could not exec this, or "" when it can."""
        if self.source == SOURCE_MISSING:
            places = "; ".join(self.looked)
            return f"The baud binary was not found. Looked, in order, at: {places}. {INSTALL_BINARY_HINT}"

        if self.source == SOURCE_CONFIGURED and not self.runnable():
            return (
                f"The configured baud binary {self.path} is gone or not executable, and a configured binary is "
                "never fallen past. Name another with drone @api host-api set-config --baud-bin <path>, or return "
                "to the automatic lookup: drone @api host-api set-config --baud-bin default"
            )

        return ""


def _is_runnable(path: Path) -> bool:
    """Whether a path is an executable regular file."""
    return path.is_file() and os.access(path, os.X_OK)


def locate_binary() -> BinaryLocation:
    """
    Walk the lookup order once, afresh, and report what answered.

    Never raises: a configured binary is reported whatever its state, so it is
    refused by name rather than fallen past.
    """
    configured = host_config.baud_bin()
    if configured is not None:
        return BinaryLocation(str(configured), SOURCE_CONFIGURED, (f"{configured} (configured)",))

    looked: List[str] = []

    # Lazy, so a machine with no checkout still reaches the home and PATH steps.
    for place, source in (
        (lambda: Path.home() / INSTALLED_BINARY_RELATIVE, SOURCE_INSTALLED),
        (lambda: repo_root() / CHECKOUT_HEADLESS_RELATIVE, SOURCE_CHECKOUT),
        (lambda: repo_root() / DEFAULT_BINARY_RELATIVE, SOURCE_CHECKOUT),
    ):
        candidate = place()
        if _is_runnable(candidate):
            return BinaryLocation(str(candidate), source, tuple(looked + [str(candidate)]))
        looked.append(f"{candidate} (present, not an executable file)" if candidate.exists() else str(candidate))

    for name in (HEADLESS_BINARY, SNAPSHOT_BINARY):
        found = shutil.which(name)
        if found:
            return BinaryLocation(found, SOURCE_PATH, tuple(looked + [f"{name!r} on PATH"]))
        looked.append(f"{name!r} on PATH")

    return BinaryLocation("", SOURCE_MISSING, tuple(looked))


def snapshot_binary() -> str:
    """The baud binary to exec, resolved afresh on every call."""
    location = locate_binary()

    problem = location.problem()
    if problem:
        raise FleetUnavailable(problem)

    if location.source == SOURCE_PATH:
        logger.info(
            "[host_api] baud resolved from PATH at %s (no configured, installed or built binary)", location.path
        )

    return location.path


def reset_snapshot_cache() -> None:
    """Forget every cached snapshot."""
    with _snapshot_guard:
        _snapshot_cache.clear()


def _flight_lock(key: str) -> threading.Lock:
    """The lock that makes one key's refresh single-flight."""
    with _snapshot_guard:
        return _snapshot_flights.setdefault(key, threading.Lock())


def _cached_snapshot(key: str) -> Optional[Dict[str, Any]]:
    """
    The cached envelope for one key, if it is still young enough.

    A deep copy: handing out the cached object lets one caller's edit reach
    every caller for the rest of the TTL.
    """
    with _snapshot_guard:
        entry = _snapshot_cache.get(key)
    if entry is None:
        return None

    stored_at, envelope = entry
    if time.monotonic() - stored_at > SNAPSHOT_TTL_SECONDS:
        return None
    return copy.deepcopy(envelope)


def read_snapshot(project: str = "") -> Dict[str, Any]:
    """
    Read the fleet snapshot from BAUD, coalesced and briefly cached.

    A failure is never cached, so a binary that comes back works on the next request.
    """
    cached = _cached_snapshot(project)
    if cached is not None:
        return cached

    with _flight_lock(project):
        # Re-checked inside the lock: the flight we queued behind has just filled it.
        cached = _cached_snapshot(project)
        if cached is not None:
            return cached

        envelope = _read_snapshot_uncached(project)
        with _snapshot_guard:
            _snapshot_cache[project] = (time.monotonic(), copy.deepcopy(envelope))
        return envelope


def _read_snapshot_uncached(project: str = "") -> Dict[str, Any]:
    """Exec BAUD and return its envelope. The real read, every time."""
    if not SNAPSHOT_READY:
        logger.info("[host_api] fleet snapshot requested while the exec is gated")
        raise FleetUnavailable(_NOT_READY)

    command = [snapshot_binary(), "--snapshot"]
    if project:
        command += ["--project", project]

    # BAUD walks UP from its cwd to find a root; a server started from / finds none.
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
        logger.warning("[host_api] fleet snapshot reported a read failure: %s", error)
        raise FleetUnavailable(str(error))

    branches = envelope.get("branches") or []
    json_handler.log_operation(
        "host_api_fleet_read",
        {"project": envelope.get("project"), "branches": len(branches), "requested": project or "anchor"},
    )

    return envelope


def list_projects() -> Dict[str, Any]:
    """Read BAUD's project census — the rows a switcher menu shows."""
    if not SNAPSHOT_READY:
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
        logger.warning("[host_api] project census reported a failure: %s", error)
        raise FleetUnavailable(str(error))

    projects = envelope.get("projects") or []
    json_handler.log_operation("host_api_project_census", {"projects": len(projects)})

    return envelope


def read_roster() -> Dict[str, Any]:
    """
    Read BAUD's cross-project roster — every working agent, everywhere.

    An empty `branches` is a true answer, not an error. The verb takes no
    arguments: `--roster --project X` exits 2, hence FleetMisuse on empty stdout.
    """
    if not SNAPSHOT_READY:
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
        logger.warning("[host_api] roster reported a failure: %s", error)
        raise FleetUnavailable(str(error))

    branches = envelope.get("branches") or []
    json_handler.log_operation("host_api_roster", {"branches": len(branches)})

    return envelope


def resolve_branch(project: str, branch: str) -> Optional[Dict[str, Any]]:
    """One branch's row from one project's snapshot — the attach lane's census."""
    wanted = branch.strip().lstrip("@")
    envelope = read_snapshot(project)
    for row in envelope.get("branches") or []:
        if row.get("name") == wanted:
            return row
    return None


def read_rooms(project: str = "") -> Dict[str, Any]:
    """Project the snapshot down to rooms BAUD made."""
    snapshot = read_snapshot(project)

    branches = snapshot.get("branches") or []
    with_rooms = [branch for branch in branches if branch.get("has_room")]

    return {
        "project": snapshot.get("project"),
        "generated_at": snapshot.get("generated_at"),
        # Raw: joining them to branches would own BAUD's session-naming convention.
        "live_agent_sessions": snapshot.get("live_agent_sessions") or [],
        "branches_with_rooms": with_rooms,
    }


def _run_headless(args: list, timeout: int, what: str) -> Dict[str, Any]:
    """Run one headless baud verb and return its envelope."""
    command = [snapshot_binary()] + list(args)

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
        # Exit 2: BAUD never ran, so the verb did not happen; the fault is our argv.
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

    `project` is sent verbatim: it is a key in BAUD's census.
    """
    command = ["--end-room", branch]
    if project:
        command += ["--project", project]

    envelope = _run_headless(command, END_ROOM_TIMEOUT_SECONDS, "room kill")

    # Otherwise the cached snapshot shows the room just ended as still standing.
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
