# =================== AIPass ====================
# Name: lane_process.py
# Description: The lane's process seen from outside — alive, really a backup lane for this root, and how to end it
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""A running lane's process, seen from another process (DPLAN-0412).

Read through psutil, already a dependency of the package, so the same code
answers on Linux, macOS and Windows; nothing here reads ``/proc`` itself.

Two guards stand between a running file and a signal:

* :func:`live_lane` — the pid is alive, not a zombie, and the process started
  no later than the lane did. A process younger than the lane's
  ``started_at`` holds a recycled pid: the lane it named is gone.
* :func:`lane_for_root` — the process's command line is a backup lane for
  this root: backup's entry point, then the verb the file names, then this
  root (as given, or a registered name that resolves to it).

On Windows, psutil's terminate is TerminateProcess: the lane gets no SIGTERM
handler run, so its running file is left for the next reader to clear.
"""

from datetime import datetime
from pathlib import Path

import psutil

from aipass.prax import logger

from ..audit import trail
from ..project.registry import list_projects, lookup_project

#: Seconds a lane's process may appear to start after its started_at: the
#: instant is written in whole seconds, after the interpreter came up.
STARTED_SLACK_SECONDS = 2.0

#: How long kill() is given to take the process after the polite wait.
KILL_WAIT_SECONDS = 5.0

ENTRY_SCRIPT = "backup.py"
ENTRY_MODULE = "aipass.backup.apps.backup"
LEGACY_VERB = "backup"


def open_process(pid: int) -> psutil.Process | None:
    """The one seam to the process table: the process for a pid, or None when there is none.

    Args:
        pid: A process id read off a running file.

    Returns:
        psutil's handle, or None when no such process exists.
    """
    try:
        return psutil.Process(pid)
    except (psutil.NoSuchProcess, ValueError) as exc:
        logger.info(f"[backup] lane process: no process {pid}: {exc}")
        return None


def _started_epoch(entry: dict) -> float | None:
    """The entry's started_at as a POSIX timestamp, None when it cannot be read."""
    try:
        return datetime.fromisoformat(str(entry.get("started_at"))).timestamp()
    except ValueError as exc:
        logger.info(f"[backup] lane process: unreadable started_at {entry.get('started_at')!r}: {exc}")
        return None


def live_lane(entry: dict) -> psutil.Process | None:
    """The live process a running entry names, or None when the entry is stale.

    Args:
        entry: A running file's document.

    Returns:
        The process, when its pid is alive, not a zombie, and no younger than
        the lane; else None.
    """
    pid = entry.get("pid")
    started = _started_epoch(entry)
    if not isinstance(pid, int) or started is None:
        return None
    proc = open_process(pid)
    if proc is None:
        return None
    try:
        stale = proc.status() == psutil.STATUS_ZOMBIE or proc.create_time() > started + STARTED_SLACK_SECONDS
    except psutil.NoSuchProcess as exc:
        logger.info(f"[backup] lane process: {pid} went while being read: {exc}")
        stale = True
    except psutil.AccessDenied as exc:
        # Alive but unreadable: listed, and the stop guard will refuse to signal it.
        logger.info(f"[backup] lane process: {pid} unreadable: {exc}")
        stale = False
    return None if stale else proc


def _same_root(word: str, project_root: str) -> bool:
    """True when a command-line word names project_root: the path, or a registered name for it."""
    target = Path(project_root)
    if word.startswith("@"):
        found = lookup_project(word[1:])
        return found is not None and Path(found) == target
    return Path(word) == target or (not Path(word).is_absolute() and lookup_project(word) == project_root)


def _names_root(words: list[str], verb: str, project_root: str) -> bool:
    """True when the words after the verb name this root (all --registered names every registered one)."""
    if any(_same_root(word, project_root) for word in words if not word.startswith("--")):
        return True
    if verb == "all" and "--registered" in words:
        return any(
            isinstance(entry, dict) and Path(str(entry.get("path", ""))) == Path(project_root)
            for entry in list_projects().values()
        )
    return False


def cmdline_is_lane(cmdline: list[str], verb: str, project_root: str) -> bool:
    """True when a command line is backup running ``verb`` for ``project_root``.

    Backup's entry point (``.../backup.py`` or ``-m aipass.backup.apps.backup``),
    then the verb, then the root; the legacy ``backup <root>`` form counts for
    snapshot, versioned and all.

    Args:
        cmdline: The process's argv.
        verb: The verb the running file names.
        project_root: The root the running file lives under.

    Returns:
        Whether the process may be signalled for that lane.
    """
    for index, word in enumerate(cmdline):
        if Path(word).name != ENTRY_SCRIPT and word != ENTRY_MODULE:
            continue
        rest = cmdline[index + 1 :]
        if not rest:
            return False
        said = rest[0]
        if said == verb or (said == LEGACY_VERB and verb in ("snapshot", "versioned", "all")):
            return _names_root(rest[1:], verb, project_root)
        return False
    return False


def lane_for_root(proc: psutil.Process, entry: dict, project_root: str) -> str | None:
    """Refuse to signal a process that is not this root's lane.

    Args:
        proc: The live process the entry names.
        entry: The running file's document.
        project_root: The root the stop was asked for.

    Returns:
        None when the process is the lane; else the reason it is not signalled.
    """
    try:
        cmdline = proc.cmdline()
    except psutil.AccessDenied as exc:
        return f"cannot read its command line ({exc})"
    except psutil.NoSuchProcess as exc:
        return f"it went while being read ({exc})"
    if cmdline_is_lane(cmdline, str(entry.get("verb")), project_root):
        return None
    return f"its command line is not a backup {entry.get('verb')} for this root: {' '.join(cmdline)}"


def end_process(proc: psutil.Process, wait_seconds: float) -> str:
    """SIGTERM, wait, SIGKILL after; reap either way.

    Args:
        proc: The lane's process, already through both guards.
        wait_seconds: How long SIGTERM is given before SIGKILL.

    Returns:
        "terminated" when it went on SIGTERM, "killed" when it took SIGKILL.
    """
    try:
        proc.terminate()
        proc.wait(timeout=wait_seconds)
    except psutil.NoSuchProcess as exc:
        logger.info(f"[backup] lane process: already gone on terminate: {exc}")
    except psutil.TimeoutExpired as exc:
        logger.warning(f"[backup] lane process: {proc.pid} outlived SIGTERM by {wait_seconds}s, killing: {exc}")
        _kill(proc)
        trail.log_operation("lane_killed", {"pid": proc.pid, "waited_seconds": wait_seconds})
        return "killed"
    trail.log_operation("lane_terminated", {"pid": proc.pid})
    return "terminated"


def _kill(proc: psutil.Process) -> None:
    """SIGKILL and reap; a process already gone is the outcome wanted."""
    try:
        proc.kill()
        proc.wait(timeout=KILL_WAIT_SECONDS)
    except psutil.NoSuchProcess as exc:
        logger.info(f"[backup] lane process: already gone on kill: {exc}")
    except psutil.TimeoutExpired as exc:
        logger.warning(f"[backup] lane process: {proc.pid} not reaped after SIGKILL: {exc}")


# =============================================
