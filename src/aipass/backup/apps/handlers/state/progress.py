# =================== AIPass ====================
# Name: progress.py
# Description: Running-lane progress files — .backup/running/<lane>.json, written by the lane, read by status and stop
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Running-lane progress files (DPLAN-0412).

One file per lane in flight, ``<project>/.backup/running/<lane>.json``, written
by the lane itself whoever started it (phone, terminal, daemon). The document
is the backup door contract's ``running`` entry exactly
(src/aipass/devpulse/docs.local/backup_door_contract.md, "running"); this file
names its fields and does not retype the shape.

The writer, :class:`LaneProgress`, writes the entry with ``progress`` null as
soon as the lane knows it is running, rewrites it from the lane's per-file
callback at most once a second on :func:`now`, and removes it on close. Every
write goes through the json service's ``write_json``, which stages a temp file
beside the target and renames it over, so a reader never sees half a document.

The reader, :func:`read_running`, lists the entries whose process is alive and
removes the rest: a pid that is gone, a zombie, or a pid that now belongs to a
process younger than the lane (a recycled pid) is stale.
"""

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from aipass.prax import logger

from ..audit import trail
from ..json import json_handler
from ..path.builder import backup_root
from . import lane_process

RUNNING_DIRNAME = "running"
WRITE_INTERVAL_SECONDS = 1.0

#: The lanes that do work and so write a file, in the contract's order.
WORK_LANES = ("snapshot", "versioned", "drive_sync")


def now() -> float:
    """The clock the progress files read: seconds since the epoch.

    One name so a test can move time instead of sleeping through it.
    """
    return time.time()


def _iso(moment: float) -> str:
    """A POSIX timestamp as the contract's ISO instant, UTC, whole seconds."""
    return datetime.fromtimestamp(moment, timezone.utc).isoformat(timespec="seconds")


def running_dir(project_root: str) -> Path:
    """The directory a project's running files live in: ``<root>/.backup/running/``."""
    return backup_root(project_root) / RUNNING_DIRNAME


class LaneProgress:
    """The one writer of a lane's running file.

    Use as a context manager around the lane's run: entering writes the entry
    (``progress`` null), leaving removes the file on every exit path.

    Args:
        project_root: The project the lane works on.
        lane: The work being done: snapshot, versioned or drive_sync.
        verb: What was invoked: the lane's own name, or ``all``.
        clock: Seconds-since-epoch source; :func:`now` when None.
    """

    def __init__(self, project_root: str, lane: str, verb: str, clock: Callable[[], float] | None = None) -> None:
        self.project_root = project_root
        self.path = running_dir(project_root) / f"{lane}.json"
        self._clock = clock
        self._last_write: float | None = None
        self.entry: dict = {"verb": verb, "lane": lane, "pid": os.getpid(), "started_at": None, "progress": None}

    def _now(self) -> float:
        """Read the injected clock, else the module's."""
        return self._clock() if self._clock is not None else now()

    def __enter__(self) -> "LaneProgress":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def start(self) -> None:
        """Announce the lane: write the entry with ``progress`` null."""
        moment = self._now()
        self.entry["started_at"] = _iso(moment)
        self._write(moment)

    def plan(self, total: int, bytes_total: int | None = None) -> None:
        """The lane knows its total: progress becomes counts at zero.

        Args:
            total: Files the lane will go through.
            bytes_total: Planned bytes, or None when the lane does not know.
        """
        self.entry["progress"] = {
            "done": 0,
            "total": total,
            "failed": 0,
            "bytes_done": 0,
            "bytes_total": bytes_total,
            "current": None,
            "updated_at": None,
        }
        self._maybe_write()

    def file_done(self, current: str, nbytes: int = 0, ok: bool = True) -> None:
        """Count one finished file; rewrite the file if a second has passed.

        Args:
            current: The file's path as the lane names it.
            nbytes: Bytes this file copied or uploaded (0 when unchanged).
            ok: False when the file failed.
        """
        counts = self.entry["progress"]
        if counts is None:
            # A callback before plan() is a lane bug; count nothing rather than invent a total.
            logger.warning(f"[backup] progress: file_done before plan for {self.path.name}")
            return
        counts["done"] += 1
        counts["failed"] += 0 if ok else 1
        counts["bytes_done"] += max(nbytes, 0)
        counts["current"] = current
        self._maybe_write()

    def _maybe_write(self) -> None:
        """Write unless the last write was under WRITE_INTERVAL_SECONDS ago."""
        moment = self._now()
        if self._last_write is not None and moment - self._last_write < WRITE_INTERVAL_SECONDS:
            return
        self._write(moment)

    def _write(self, moment: float) -> None:
        """Write the entry atomically, into a store that already exists.

        Never scaffolds: a lane refused for a missing root must not leave a
        ``.backup/`` behind. A failed write is logged and the run goes on: the
        file reports the work, it is not the work.
        """
        self._last_write = moment
        if not backup_root(self.project_root).is_dir():
            return
        if self.entry["progress"] is not None:
            self.entry["progress"]["updated_at"] = _iso(moment)
        if not json_handler.write_json(self.path, self.entry):
            logger.warning(f"[backup] progress: could not write {self.path}")

    def close(self) -> None:
        """Remove the running file; a file already gone is fine."""
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"[backup] progress: could not remove {self.path}: {exc}")


def _remove_stale(path: Path, reason: str) -> None:
    """Remove a running file that no live lane answers for, and say so in the trail."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(f"[backup] progress: could not remove stale {path}: {exc}")
        return
    trail.log_operation("running_stale_removed", {"file": str(path), "reason": reason})


def read_running(project_root: str) -> list[dict]:
    """The lanes in flight for a project, the contract's ``running`` list.

    A file whose process is not a live lane (gone, a zombie, or a pid younger
    than the lane) is stale: left out and removed. So is a file that is not a
    JSON object, which no lane writes. Nothing is created: a root with no
    store reads ``[]``.

    Args:
        project_root: The project root.

    Returns:
        One entry per live lane, in WORK_LANES order.
    """
    folder = running_dir(project_root)
    if not folder.is_dir():
        return []
    listed: list[dict] = []
    for lane in WORK_LANES:
        path = folder / f"{lane}.json"
        if not path.exists():
            continue
        entry = json_handler.read_json(path)
        if not isinstance(entry, dict):
            if path.exists():
                _remove_stale(path, "unreadable")
            continue
        if lane_process.live_lane(entry) is None:
            _remove_stale(path, "process gone")
            continue
        listed.append(entry)
    return listed


# =============================================
