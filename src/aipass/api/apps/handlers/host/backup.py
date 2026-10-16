# =================== AIPass ====================
# Name: backup.py
# Description: Host API Backup Handler — the backup door: start a lane, read a job, read the store
# Version: 1.0.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""
Host API Backup Handler

The backup door (DPLAN-0411): the logic behind POST /v1/backup/run, GET
/v1/backup/job and GET /v1/backup/status. Every shape on the wire is the one in
devpulse's backup door contract; this module names none of its own.

THE DOOR OWNS NO MECHANISM
------------------------------------------------------------------------
@backup owns the lanes and `status --json`. This module imports no subprocess
machinery and reaches @backup only through drone.route_command, the verb lane's
pattern. The argv per lane is the contract's table and nothing more: snapshot,
versioned and all take --quiet, drive_sync has none.

The project resolves through the READ lane's resolver: the seat through the
local citizen registry (matched case-insensitively), any other name through
@baud's census. This module never composes a path and never hands @backup a
@name, only the root the resolver produced.

START AND POLL
------------------------------------------------------------------------
A lane can take minutes, so a run is a job: the route answers 202 with the job
at once and the command runs on a worker thread. The phone polls the job and,
when the job is forgotten, reads the store through the status route instead.

Jobs live in this process's memory, keyed by a short id. One job per project
and lane runs at a time; different lanes overlap, and @backup's own locks
decide what that means. A finished job is kept an hour, then dropped, and a
server restart forgets every job.

Classes:
    JobUnknown        - No job by that id on this server (404 job_unknown)
    StatusJsonMissing - @backup answered status with something that is not one JSON object
    JobTable          - The in-memory job table and its lock

Functions:
    start_run()    - Start one lane for one project, answer the job
    read_job()     - One job, by id
    read_status()  - @backup's status for one project, plus this server's running jobs
    answer()       - Run one of the three and answer (status, body) for the route
    start_worker() - Start a daemon thread, the table's default starter
"""

import json
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler
from aipass.api.apps.handlers.host import denials as host_denials
from aipass.api.apps.handlers.host import reads as host_reads
from aipass.api.apps.handlers.host.verbs import VerbRefused, VerbUnavailable

# @drone's public package surface — the router every operator uses.
import aipass.drone as drone

BACKUP = "@backup"

#: The four lanes on the wire and the flags each one takes after the root.
#: drive_sync has no --quiet; passing one would be an argument it refuses.
LANES: Dict[str, List[str]] = {
    "snapshot": ["--quiet"],
    "versioned": ["--quiet"],
    "all": ["--quiet"],
    "drive_sync": [],
}

RUN_TIMEOUT_SECONDS = 1800

# status reads the store's index; --sizes walks it, which is seconds, not minutes.
STATUS_TIMEOUT_SECONDS = 120

#: The job's summary is the tail of the command's output, verbatim, this long at most.
SUMMARY_CHARS = 600

#: How long a finished job stays readable.
KEEP_FINISHED = timedelta(hours=1)

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"

STATUS_JSON_MISSING = (
    "@backup's status --json is not available on this machine; the backup status cannot be read until it is"
)

WORKER_DIED = "The backup worker stopped before @backup answered; the reason is in this host's log"


class JobUnknown(Exception):
    """No job by that id on this server: never started, dropped after an hour, or lost to a restart."""


class StatusJsonMissing(VerbUnavailable):
    """@backup answered status with something that is not one JSON object."""


def _utc_now() -> datetime:
    """The table's default clock: now, in UTC."""
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    """An instant as the contract writes it, e.g. 2026-10-16T07:30:00+00:00."""
    return moment.isoformat(timespec="seconds")


def start_worker(target: Callable[..., None], args: Tuple[Any, ...]) -> threading.Thread:
    """
    Run *target* on a daemon thread, the table's default starter.

    Daemon, so a run still going when the server stops never holds the process
    open; @backup's own store survives the interruption.

    Args:
        target: The worker function.
        args: Its arguments.

    Returns:
        The started thread.
    """
    worker = threading.Thread(target=target, args=args, daemon=True, name="host-api-backup")
    worker.start()
    return worker


class JobTable:
    """
    The jobs this server started, in memory, behind one lock.

    Args:
        clock: Answers now as an aware datetime. Injectable so the hour can be tested.
        start: Starts a worker, start_worker's shape. Injectable so a test runs it in step.
    """

    def __init__(
        self,
        clock: Optional[Callable[[], datetime]] = None,
        start: Optional[Callable[[Callable[..., None], Tuple[Any, ...]], Any]] = None,
    ) -> None:
        self.clock = clock or _utc_now
        self.start = start or start_worker
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def begin(self, project: str, lane: str, root: Path) -> Dict[str, Any]:
        """
        Record a new running job and start its worker.

        Args:
            project: The project as the caller named it.
            lane: One of LANES.
            root: The resolved project root.

        Returns:
            The job object as the route answers it.

        Raises:
            VerbRefused: The same lane is already running for this project.
            VerbUnavailable: The worker could not be started.
        """
        with self._lock:
            self._sweep()
            for record in self._jobs.values():
                if record["root"] == root and record["job"]["lane"] == lane and record["finished"] is None:
                    since = record["job"]["started_at"]
                    raise VerbRefused(f"{lane} already running for {project} since {since}")

            job_id = uuid.uuid4().hex[:6]
            while job_id in self._jobs:
                job_id = uuid.uuid4().hex[:6]

            started = _iso(self.clock())
            job = {"job": job_id, "project": project, "lane": lane, "state": STATE_RUNNING, "started_at": started}
            self._jobs[job_id] = {"root": root, "job": job, "finished": None}

        argv = [str(root)] + LANES[lane]
        try:
            self.start(_work, (self, job_id, lane, argv))
        except RuntimeError as e:
            # No thread, no run: the job never existed as far as anyone polling knows.
            with self._lock:
                self._jobs.pop(job_id, None)
            raise VerbUnavailable(f"The backup worker could not be started: {e}") from e

        return dict(job)

    def finish(self, job_id: str, exit_code: Optional[int], summary: str, error: Optional[str]) -> None:
        """
        Close a running job: done on exit 0, failed on anything else.

        Args:
            job_id: The job to close.
            exit_code: The command's exit code, None when it never answered.
            summary: The tail of the command's output.
            error: The sentence when the run died behind the door, else None.
        """
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                logger.warning("[host_api] backup job %s finished after it was dropped", job_id)
                return
            finished = self.clock()
            record["finished"] = finished
            record["job"].update(
                {
                    "state": STATE_DONE if exit_code == 0 and error is None else STATE_FAILED,
                    "finished_at": _iso(finished),
                    "exit": exit_code,
                    "summary": summary,
                    "error": error,
                }
            )

    def read(self, job_id: str) -> Dict[str, Any]:
        """
        One job, by id.

        Raises:
            JobUnknown: No job by that id.
        """
        with self._lock:
            self._sweep()
            record = self._jobs.get(job_id)
            if record is None:
                raise JobUnknown(
                    f"No backup job {job_id!r} on this server: finished jobs are kept an hour and a restart "
                    "forgets them all; /v1/backup/status reads the store"
                )
            return dict(record["job"])

    def running(self, root: Path) -> List[Dict[str, Any]]:
        """This server's in-flight jobs for one project root, as the status route lists them."""
        with self._lock:
            return [
                {"job": record["job"]["job"], "lane": record["job"]["lane"], "started_at": record["job"]["started_at"]}
                for record in self._jobs.values()
                if record["root"] == root and record["finished"] is None
            ]

    def _sweep(self) -> None:
        """Drop every job that finished more than KEEP_FINISHED ago. The caller holds the lock."""
        cutoff = self.clock() - KEEP_FINISHED
        for job_id in [key for key, record in self._jobs.items() if record["finished"] and record["finished"] < cutoff]:
            del self._jobs[job_id]


#: The one table this server keeps. Replaced whole by a test, never reached into.
JOBS = JobTable()


def _work(table: JobTable, job_id: str, lane: str, argv: List[str]) -> None:
    """
    Run one lane through drone and close its job. Runs on the worker thread.

    Args:
        table: The table the job lives in.
        job_id: The job to close.
        lane: The @backup verb.
        argv: The root, then the lane's flags.
    """
    try:
        result = drone.route_command(BACKUP, lane, argv, timeout=RUN_TIMEOUT_SECONDS)
    except drone.RoutingError as e:
        # The door died behind us: a failed job carrying drone's sentence, as the contract says.
        logger.warning("[host_api] backup %s job %s could not finish: %s", lane, job_id, e)
        table.finish(job_id, None, "", str(e).strip() or type(e).__name__)
        return
    except Exception as e:
        # Anything else would leave the job running forever and the lane refused
        # until a restart. The words go to the log; the job gets a fixed sentence.
        logger.error("[host_api] backup %s job %s worker failed: %s", lane, job_id, e, exc_info=e)
        table.finish(job_id, None, "", WORKER_DIED)
        return

    output = "\n".join(part.rstrip("\n") for part in (result.stdout, result.stderr) if part and part.strip())
    table.finish(job_id, result.exit_code, output[-SUMMARY_CHARS:], None)
    json_handler.log_operation("host_api_backup_finished", {"job": job_id, "lane": lane, "exit": result.exit_code})
    logger.info("[host_api] backup %s job %s finished with exit %s", lane, job_id, result.exit_code)


def _root_of(project: str) -> Path:
    """
    Resolve a project name to its root through the read lane's resolver.

    Args:
        project: The name as the caller sent it; the seat in any case.

    Returns:
        The project's absolute root.

    Raises:
        VerbRefused: No project named, or one the census does not know.
        VerbUnavailable: The registry or the census could not answer.
    """
    if not project or not project.strip():
        raise VerbRefused("A project is required on the backup door — it is never inferred from the server's seat")

    try:
        if host_reads._is_seated(project):
            return host_reads.resolve_root(host_reads.ROOT_AIPASS)
        return host_reads.resolve_root(host_reads.ROOT_PROJECT, project.strip())
    except host_reads.ReadRefused as e:
        raise VerbRefused(str(e)) from e
    except host_reads.ReadUnavailable as e:
        raise VerbUnavailable(str(e)) from e


def _door() -> None:
    """
    Check that drone can find @backup before a job is opened.

    Raises:
        VerbUnavailable: drone cannot resolve @backup on this machine.
    """
    try:
        drone.resolve_branch(BACKUP)
    except drone.RoutingError as e:
        logger.error("[host_api] drone cannot reach %s: %s", BACKUP, e)
        raise VerbUnavailable(f"{BACKUP} could not be reached: {e}") from e


def start_run(project: str, lane: str) -> Dict[str, Any]:
    """
    Start one lane for one project.

    Args:
        project: The project, verbatim from the request.
        lane: One of LANES.

    Returns:
        The running job, which the route answers with 202.

    Raises:
        VerbRefused: No lane, an unknown lane, no project, an unknown project,
            or the same lane already running for this project.
        VerbUnavailable: The census, drone or the worker could not answer.
    """
    if lane not in LANES:
        named = f"Unknown lane {lane!r}" if lane else "A lane is required"
        raise VerbRefused(f"{named} — the backup door runs {', '.join(LANES)}")

    root = _root_of(project)
    _door()
    job = JOBS.begin(project, lane, root)

    json_handler.log_operation("host_api_backup_started", {"job": job["job"], "project": project, "lane": lane})
    logger.info("[host_api] backup %s started for %s as job %s", lane, project, job["job"])
    return job


def read_job(job_id: str) -> Dict[str, Any]:
    """
    One job, by id.

    Args:
        job_id: The id the run route answered.

    Returns:
        The job object.

    Raises:
        JobUnknown: No job by that id on this server.
    """
    return JOBS.read(job_id.strip())


def read_status(project: str, sizes: bool = False) -> Dict[str, Any]:
    """
    @backup's status for one project, with project, root and running added.

    Args:
        project: The project, verbatim from the request.
        sizes: Ask @backup to walk the store for its two sizes.

    Returns:
        @backup's object, then "project" as asked, "root" as resolved and
        "running", this server's in-flight jobs for the project.

    Raises:
        VerbRefused: No project, or an unknown one.
        StatusJsonMissing: @backup answered something that is not one JSON object.
        VerbUnavailable: The census or @backup could not answer.
    """
    root = _root_of(project)
    args = [str(root), "--json"] + (["--sizes"] if sizes else [])

    try:
        result = drone.route_command(BACKUP, "status", args, timeout=STATUS_TIMEOUT_SECONDS)
    except drone.RoutingError as e:
        logger.error("[host_api] drone could not run %s status: %s", BACKUP, e)
        raise VerbUnavailable(f"{BACKUP} status could not be run: {e}") from e

    if result.exit_code != 0:
        raise VerbUnavailable(f"{BACKUP} status exited {result.exit_code}: {(result.stderr or result.stdout).strip()}")

    try:
        answered = json.loads(result.stdout or "")
    except ValueError as e:
        logger.warning("[host_api] %s status answered no JSON object: %s", BACKUP, e)
        raise StatusJsonMissing(STATUS_JSON_MISSING) from e
    if not isinstance(answered, dict):
        raise StatusJsonMissing(STATUS_JSON_MISSING)

    answered["project"] = project
    answered["root"] = str(root)
    answered["running"] = JOBS.running(root)
    return answered


def answer(call: Callable[..., Dict[str, Any]], *args: Any) -> Tuple[int, Dict[str, Any]]:
    """
    Run one of the three and answer (status, body), with no web framework in it.

    Args:
        call: start_run, read_job or read_status.
        *args: Its arguments.

    Returns:
        (200, the answer), or (status, {"code", "message", ...}): 400
        verb_refused and 404 job_unknown carry their own sentence; 503
        verb_unavailable carries the fixed one and a ref into this host's log,
        or STATUS_JSON_MISSING when @backup's status --json is absent.
    """
    try:
        return 200, call(*args)
    except JobUnknown as e:
        return 404, {"code": "job_unknown", "message": str(e)}
    except VerbRefused as e:
        return 400, {"code": "verb_refused", "message": str(e)}
    except StatusJsonMissing as e:
        ref = host_denials.logged(e, 503, "verb_unavailable")
        return 503, {"code": "verb_unavailable", "message": STATUS_JSON_MISSING, "ref": ref}
    except VerbUnavailable as e:
        ref = host_denials.logged(e, 503, "verb_unavailable")
        return 503, {"code": "verb_unavailable", "message": host_denials.SENTENCES["verb_unavailable"], "ref": ref}
