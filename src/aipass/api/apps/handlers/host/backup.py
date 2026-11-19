# =================== AIPass ====================
# Name: backup.py
# Description: Host API Backup Handler — the backup door: start and stop a lane, read a job, the store, the schedule
# Version: 1.4.0
# Created: 2026-10-16
# Modified: 2026-11-15
# =============================================

"""
Host API Backup Handler
Reference: docs/host_backup.md. Reaches @backup only through drone.route_command; owns no subprocess."""

import json
import re
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

import aipass.drone as drone

BACKUP = "@backup"

# drive_sync has no --quiet; passing one would be an argument it refuses.
LANES: Dict[str, List[str]] = {
    "snapshot": ["--quiet"],
    "all": ["--quiet"],
    "drive_sync": [],
}

# drive_sync has no limit by the owner's ruling: a rebuild is hours, its own stop ends it early.
RUN_LIMIT_SECONDS: Dict[str, Optional[int]] = {"snapshot": 1800, "all": 86400, "drive_sync": None}

# shortcut: drone's router has no no-deadline mode, so an unlimited lane gets ten years; use drone's when it has one.
UNLIMITED_SECONDS = 10 * 365 * 86400

# @backup's stop waits up to 30 s for a lane before SIGKILL; this leaves it room.
CANCEL_TIMEOUT_SECONDS = 60

# drone's hang guard is the backstop past the limit: it terminates, then kills, after one second.
LIMIT_GRACE_SECONDS = CANCEL_TIMEOUT_SECONDS + 60

STOPPED_EXIT = 130

# status reads the store's index; --sizes walks it, which is seconds, not minutes.
STATUS_TIMEOUT_SECONDS = 120

SUMMARY_CHARS = 600

KEEP_FINISHED = timedelta(hours=1)

STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_STOPPED = "stopped"
STATE_FAILED = "failed"

STATUS_JSON_MISSING = (
    "@backup's status --json is not available on this machine; the backup status cannot be read until it is"
)

WORKER_DIED = "The backup worker stopped before @backup answered; the reason is in this host's log"

JOB_UNKNOWN = (
    "No backup job by that id on this server: finished jobs are kept an hour and a restart "
    "forgets them all; /v1/backup/status reads the store"
)


# @backup's not-running line is one short sentence; anything longer is not that line.
MAX_LINE_CHARS = 300

STOP_FAILED = "@backup stop exited non-zero with nothing on stdout"

# @backup's schedule asks @daemon's queue with 60 s to answer; this leaves it room.
SCHEDULE_TIMEOUT_SECONDS = 120

# shortcut: @backup exits 2 for a refusal and a fault it names alike, so both are 400; split when its codes do.
SCHEDULE_REFUSED_EXIT = 2

# Each frequency's fields, in the order @backup's set form takes them after the frequency.
SCHEDULE_SHAPES = {"daily": ("time",), "weekly": ("weekday", "time"), "monthly": ("day", "time")}

SCHEDULE_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

SCHEDULE_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class JobUnknown(Exception):
    """No job by that id on this server: never started, dropped after an hour, or lost to a restart."""


class NotRunning(Exception):
    """@backup's stop exited non-zero: nothing of that lane runs for the project. Carries its first stdout line."""


class StatusJsonMissing(VerbUnavailable):
    """@backup answered status with something that is not one JSON object."""


def _utc_now() -> datetime:
    """The table's default clock: now, in UTC."""
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    """An instant as the wire writes it, e.g. 2026-10-16T07:30:00+00:00."""
    return moment.isoformat(timespec="seconds")


def start_worker(target: Callable[..., None], args: Tuple[Any, ...]) -> threading.Thread:
    """Run *target* on a daemon thread, the table's default starter."""
    # Daemon: a run still going never holds a stopping server open; @backup's store survives it.
    worker = threading.Thread(target=target, args=args, daemon=True, name="host-api-backup")
    worker.start()
    return worker


def start_alarm(seconds: float, action: Callable[[], None]) -> threading.Timer:
    """Run *action* once after *seconds* on a daemon timer, the table's default alarm."""
    alarm = threading.Timer(seconds, action)
    alarm.daemon = True
    alarm.start()
    return alarm


class JobTable:
    """The jobs this server started, in memory, behind one lock."""

    def __init__(
        self,
        clock: Optional[Callable[[], datetime]] = None,
        start: Optional[Callable[[Callable[..., None], Tuple[Any, ...]], Any]] = None,
        after: Optional[Callable[[float, Callable[[], None]], Any]] = None,
    ) -> None:
        self.clock = clock or _utc_now
        self.start = start or start_worker
        self.after = after or start_alarm
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def begin(self, project: str, lane: str, root: Path) -> Dict[str, Any]:
        """Record a new running job and start its worker."""
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
        """Close a running job: done on exit 0, stopped on STOPPED_EXIT, failed on anything else."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                logger.warning("[host_api] backup job %s finished after it was dropped", job_id)
                return
            finished = self.clock()
            record["finished"] = finished
            state = STATE_FAILED
            if error is None and exit_code == 0:
                state = STATE_DONE
            elif error is None and exit_code == STOPPED_EXIT:
                state = STATE_STOPPED
            record["job"].update(
                {
                    "state": state,
                    "finished_at": _iso(finished),
                    "exit": exit_code,
                    "summary": summary,
                    "error": error,
                }
            )

    def read(self, job_id: str) -> Dict[str, Any]:
        """One job, by id."""
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
        """This server's in-flight jobs for one project root, the list when @backup's status has none."""
        with self._lock:
            return [
                {"job": record["job"]["job"], "lane": record["job"]["lane"], "started_at": record["job"]["started_at"]}
                for record in self._jobs.values()
                if record["root"] == root and record["finished"] is None
            ]

    def attach(self, root: Path, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """@backup's running entries, each with "job" added."""
        with self._lock:
            started = {
                record["job"]["lane"]: record["job"]["job"]
                for record in self._jobs.values()
                if record["root"] == root and record["finished"] is None
            }
        return [{**entry, "job": started.get(entry.get("verb"))} for entry in entries]

    def _sweep(self) -> None:
        """Drop every job that finished more than KEEP_FINISHED ago. The caller holds the lock."""
        cutoff = self.clock() - KEEP_FINISHED
        for job_id in [key for key, record in self._jobs.items() if record["finished"] and record["finished"] < cutoff]:
            del self._jobs[job_id]


# Replaced whole by a test, never reached into.
JOBS = JobTable()


def _work(table: JobTable, job_id: str, lane: str, argv: List[str]) -> None:
    """Run one lane through drone and close its job. Runs on the worker thread."""
    limit = RUN_LIMIT_SECONDS[lane]
    alarm = None if limit is None else table.after(limit, lambda: _end_at_limit(job_id, lane, argv[0], limit))
    timeout = UNLIMITED_SECONDS if limit is None else limit + LIMIT_GRACE_SECONDS
    try:
        result = drone.route_command(BACKUP, lane, argv, timeout=timeout)
    except drone.RoutingError as e:
        logger.warning("[host_api] backup %s job %s could not finish: %s", lane, job_id, e)
        table.finish(job_id, None, "", str(e).strip() or type(e).__name__)
        return
    except Exception as e:
        # Uncaught, the job would stay running and its lane refused until a restart.
        logger.error("[host_api] backup %s job %s worker failed: %s", lane, job_id, e, exc_info=e)
        table.finish(job_id, None, "", WORKER_DIED)
        return
    finally:
        if alarm is not None:
            alarm.cancel()

    output = "\n".join(part.rstrip("\n") for part in (result.stdout, result.stderr) if part and part.strip())
    table.finish(job_id, result.exit_code, output[-SUMMARY_CHARS:], None)
    json_handler.log_operation("host_api_backup_finished", {"job": job_id, "lane": lane, "exit": result.exit_code})
    logger.info("[host_api] backup %s job %s finished with exit %s", lane, job_id, result.exit_code)


def _end_at_limit(job_id: str, lane: str, root: str, limit: int) -> None:
    """End a lane past its limit the way a cancel does, so it exits 130 and clears its running file."""
    logger.warning("[host_api] backup %s job %s reached its %ss limit; asking @backup to stop it", lane, job_id, limit)
    try:
        drone.route_command(BACKUP, "stop", [root, lane], timeout=CANCEL_TIMEOUT_SECONDS)
    except Exception as e:
        logger.error("[host_api] backup %s job %s could not be stopped at its limit: %s", lane, job_id, e, exc_info=e)


def _root_of(project: str) -> Path:
    """Resolve a project name to its root through the read lane's resolver."""
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


def _check_lane(lane: str) -> None:
    """Refuse anything but one of the three lanes."""
    if lane not in LANES:
        named = f"Unknown lane {lane!r}" if lane else "A lane is required"
        raise VerbRefused(f"{named} — the backup door runs {', '.join(LANES)}")


def _door() -> None:
    """Check that drone can find @backup before a job is opened."""
    try:
        drone.resolve_branch(BACKUP)
    except drone.RoutingError as e:
        logger.error("[host_api] drone cannot reach %s: %s", BACKUP, e)
        raise VerbUnavailable(f"{BACKUP} could not be reached: {e}") from e


def start_run(project: str, lane: str) -> Dict[str, Any]:
    """Start one lane for one project."""
    _check_lane(lane)
    root = _root_of(project)
    _door()
    job = JOBS.begin(project, lane, root)

    json_handler.log_operation("host_api_backup_started", {"job": job["job"], "project": project, "lane": lane})
    logger.info("[host_api] backup %s started for %s as job %s", lane, project, job["job"])
    return job


def stop_run(project: str, lane: str) -> Dict[str, Any]:
    """
    Ask @backup to stop one lane for one project. The job table is not touched:
    the run's job closes by itself when its lane exits."""
    _check_lane(lane)
    root = _root_of(project)

    try:
        result = drone.route_command(BACKUP, "stop", [str(root), lane], timeout=CANCEL_TIMEOUT_SECONDS)
    except drone.RoutingError as e:
        logger.error("[host_api] drone could not run %s stop: %s", BACKUP, e)
        raise VerbUnavailable(f"{BACKUP} stop could not be run: {e}") from e

    if result.exit_code != 0:
        # stdout only: @backup prints its not-running line there, and stderr can be a traceback.
        line = ((result.stdout or "").strip().splitlines() or [""])[0][:MAX_LINE_CHARS]
        if not line:
            logger.error(
                "[host_api] backup %s stop for %s exited %s: %s", lane, project, result.exit_code, result.stderr
            )
            raise VerbUnavailable(STOP_FAILED)
        logger.info("[host_api] backup %s stop for %s exited %s: %s", lane, project, result.exit_code, line)
        raise NotRunning(line)

    message = (result.stdout or "").strip()
    json_handler.log_operation("host_api_backup_stopped", {"project": project, "lane": lane})
    logger.info("[host_api] backup %s stopped for %s: %s", lane, project, message)
    return {"project": project, "lane": lane, "stopped": True, "message": message}


def read_job(job_id: str) -> Dict[str, Any]:
    """One job, by id."""
    return JOBS.read(job_id.strip())


def read_status(project: str, sizes: bool = False) -> Dict[str, Any]:
    """@backup's status for one project, with project and root added and a job id on each running entry."""
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
    if "running" not in answered:
        logger.info("[host_api] %s status has no running list (older @backup); listing this server's jobs", BACKUP)
        answered["running"] = JOBS.running(root)
        return answered

    running = answered["running"]
    if not isinstance(running, list) or not all(isinstance(entry, dict) for entry in running):
        raise VerbUnavailable(f"{BACKUP} status answered running as {type(running).__name__}, not a list of objects")
    answered["running"] = JOBS.attach(root, running)
    return answered


def _schedule(root: Path, words: List[str]) -> str:
    """One @backup schedule call; its stdout on exit 0. Exit 2 with a sentence is @backup refusing."""
    try:
        result = drone.route_command(BACKUP, "schedule", [str(root)] + words, timeout=SCHEDULE_TIMEOUT_SECONDS)
    except drone.RoutingError as e:
        logger.error("[host_api] drone could not run %s schedule: %s", BACKUP, e)
        raise VerbUnavailable(f"{BACKUP} schedule could not be run: {e}") from e

    if result.exit_code == 0:
        return result.stdout or ""
    # The hint after the arrow is usage, and Rich wraps both, so the sentence is rejoined.
    sentence = " ".join((result.stderr or "").split("→ Try:")[0].split()).lstrip("❌ ")[:MAX_LINE_CHARS]
    if result.exit_code != SCHEDULE_REFUSED_EXIT or not sentence:
        logger.error("[host_api] %s schedule %s exited %s: %s", BACKUP, words, result.exit_code, result.stderr)
        raise VerbUnavailable(f"{BACKUP} schedule exited {result.exit_code}: {sentence}")
    logger.warning("[host_api] %s schedule %s refused: %s", BACKUP, words, sentence)
    raise VerbRefused(sentence)


def _schedule_json(root: Path) -> Dict[str, Any]:
    """@backup's schedule --json, one object, keys untouched."""
    stdout = _schedule(root, ["--json"])
    try:
        answered = json.loads(stdout)
    except ValueError as e:
        raise VerbUnavailable(f"{BACKUP} schedule --json answered no JSON object: {e}") from e
    if not isinstance(answered, dict):
        raise VerbUnavailable(f"{BACKUP} schedule --json answered {type(answered).__name__}, not an object")
    return answered


def read_schedule(project: str) -> Dict[str, Any]:
    """One project's scheduled backup, as @backup's schedule --json answers it."""
    return _schedule_json(_root_of(project))


def _schedule_words(frequency: Any, time: Any, weekday: Any, day: Any) -> List[str]:
    """@backup's set form for one frequency; a missing, malformed or stray field is refused."""
    if frequency not in SCHEDULE_SHAPES:
        named = f"Unknown frequency {frequency!r}" if frequency else "A frequency is required with its fields"
        raise VerbRefused(f"{named} — the schedule takes {', '.join(SCHEDULE_SHAPES)}")
    shape = SCHEDULE_SHAPES[frequency]
    given = {"weekday": weekday, "day": day, "time": time}
    stray = [field for field, value in given.items() if value is not None and field not in shape]
    if stray:
        raise VerbRefused(f"{frequency} takes no {' or '.join(stray)}")
    if "weekday" in shape and weekday not in SCHEDULE_WEEKDAYS:
        raise VerbRefused(f"Not a weekday: {weekday!r} — monday to sunday, lowercase")
    # type(), not isinstance: JSON true is a bool, and a bool is an int to isinstance.
    if "day" in shape and (type(day) is not int or not 1 <= day <= 31):
        raise VerbRefused(f"Not a day of the month: {day!r} — a whole number 1 to 31")
    if not isinstance(time, str) or not SCHEDULE_TIME.fullmatch(time):
        raise VerbRefused(f"Not a 24-hour HH:MM time: {time!r}")
    return [frequency] + [str(given[field]) for field in shape]


def set_schedule(
    project: str,
    on: Any = None,
    frequency: Any = None,
    time: Any = None,
    weekday: Any = None,
    day: Any = None,
) -> Dict[str, Any]:
    """
    Set a frequency with its fields, then on or off, through @backup; answer the schedule read back.
    Everything @backup would refuse for its form is refused here first, before anything is written."""
    calls: List[List[str]] = []
    if any(field is not None for field in (frequency, time, weekday, day)):
        calls.append(_schedule_words(frequency, time, weekday, day))
    if on is not None:
        if not isinstance(on, bool):
            raise VerbRefused(f"on is true or false, not {on!r}")
        calls.append(["on" if on else "off"])
    if not calls:
        raise VerbRefused("Nothing to set: send on, or a frequency with its fields")

    root = _root_of(project)
    for words in calls:
        _schedule(root, words)
    json_handler.log_operation("host_api_backup_schedule_set", {"project": project, "calls": calls})
    logger.info("[host_api] backup schedule for %s set: %s", project, calls)
    return _schedule_json(root)


def answer(call: Callable[..., Dict[str, Any]], *args: Any) -> Tuple[int, Dict[str, Any]]:
    """Run one of the door's calls and answer (status, body), with no web framework in it."""
    try:
        return 200, call(*args)
    except JobUnknown as e:
        logger.info("[host_api] backup job refused: %s", e)
        return 404, {"code": "job_unknown", "message": JOB_UNKNOWN}
    except NotRunning as e:
        return 404, {"code": "not_running", "message": str(e)}
    except VerbRefused as e:
        return 400, {"code": "verb_refused", "message": str(e)}
    except StatusJsonMissing as e:
        ref = host_denials.logged(e, 503, "verb_unavailable")
        return 503, {"code": "verb_unavailable", "message": STATUS_JSON_MISSING, "ref": ref}
    except VerbUnavailable as e:
        ref = host_denials.logged(e, 503, "verb_unavailable")
        return 503, {"code": "verb_unavailable", "message": host_denials.SENTENCES["verb_unavailable"], "ref": ref}
