# =================== AIPass ====================
# Name: discovery.py
# Description: Decentralized .daemon/ schedule file discovery
# Version: 2.8.0
# Created: 2026-06-15
# Modified: 2026-11-17
# =============================================

"""
Decentralized schedule discovery — sweeps every active citizen's .daemon/*.json
and returns validated Job dicts.
Reference: docs/schedule_contract.md"""

import json
import re
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.drone import resolve_aipass_home
from aipass.daemon.apps.handlers.json import json_handler

# @memory's front door: its apps/ are private and fail the cross-branch checklist.
# RESIDENCY_* are re-exported from @memory rather than re-spelled: two copies of a vocabulary drift silently.
from aipass.memory import RESIDENCY_CORE as RESIDENCY_CORE, RESIDENCY_RESIDENT as RESIDENCY_RESIDENT, fleet_branches
from aipass.daemon.apps.handlers.schedule import command_job
from aipass.daemon.apps.handlers.schedule.runstate import WEEKDAYS

_REPO_ROOT: Optional[Path] = None  # test seam; None resolves the AIPass home per call (see _repo_root)
_PROJECTS_DIR_NAME = "projects"

RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"

SKIP_DIRS = frozenset({"compass", "__pycache__", ".git", ".venv"})

PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

REQUIRED_JOB_KEYS = {"id", "schedule"}

# A job carries exactly one: prompt wakes the owner, command runs a drone verb and wakes nobody.
JOB_ACTION_KEYS = ("prompt", "command")
VALID_SCHEDULE_TYPES = {"daily", "hourly", "interval", "once", "rotation", "weekly", "monthly"}
# The providers ai_mail's wake_branch runs; an absent wake.provider leaves its default (claude).
VALID_WAKE_PROVIDERS = ("claude", "codex", "opencode")

SOURCE_AIPASS = "aipass"
SOURCE_EXTERNAL = "external"

# Must match the registry file name as @memory's records spell it.
_CORE_REGISTRY_NAME = "AIPASS_REGISTRY.json"

# Reads its mail live; must never be woken into an interactive session by a scheduled job.
MANAGER_CLASS = "manager"


class PassportUnreadable(Exception):
    """A passport is there but cannot be read. It may be a manager's: callers must not treat it as a worker's."""


def _source_label(record: dict, repo_root: Path) -> str:
    """A human label for WHICH registry vouched for this citizen.
    Display contract only (drone @daemon rotation and its JSON); nothing routes on it."""
    if record.get("registry") == _CORE_REGISTRY_NAME:
        return SOURCE_AIPASS

    path = Path(record["path"])
    projects_dir = repo_root / _PROJECTS_DIR_NAME

    # A citizen outside projects/ is a federated external: labelled by registry stem, never as core.
    if not path.is_relative_to(projects_dir):
        stem = str(record.get("registry", "")).replace("_REGISTRY.json", "")
        return f"{SOURCE_EXTERNAL}/{stem}" if stem else SOURCE_EXTERNAL

    return f"{_PROJECTS_DIR_NAME}/{path.relative_to(projects_dir).parts[0]}"


def _repo_root() -> Path:
    """The AIPass home the fleet sits under, resolved per call; loud when none resolves."""
    if _REPO_ROOT is not None:
        return _REPO_ROOT
    home = resolve_aipass_home().path
    if home is None:
        logger.error("[discovery] No AIPass home resolved; cannot find the fleet or the framework root")
        raise RuntimeError("No AIPass home resolved: set AIPASS_HOME to the AIPass checkout")
    return home


def active_citizens(repo_root: Optional[Path] = None) -> List[dict]:
    """Return an ordered record per active citizen, in @memory's fleet order.
    Who counts is @memory's; daemon refuses (at error level) citizens with no email or a duplicate one."""
    # Not passed through as None: patching _REPO_ROOT must still redirect the lane (temp-tree tests).
    root = Path(repo_root) if repo_root is not None else _repo_root()

    # @memory dedupes by path; daemon is email-keyed, so a shared email would double-fire.
    records = []
    seen: dict = {}
    for citizen in fleet_branches(root, name_from="registry"):
        email = citizen.get("email")
        if not email:
            logger.error(
                "[discovery] REFUSED '%s' at %s (listed active in %s): no email in the registry row — "
                "daemon addresses jobs and wakes by email, so an addressless citizen cannot own one",
                citizen.get("name", "?"),
                citizen.get("path"),
                citizen.get("registry", "?"),
            )
            continue

        if email in seen:
            logger.error(
                "[discovery] REFUSED duplicate address %s at %s (listed active in %s): "
                "already claimed by %s — daemon keys jobs and wakes by email, so a second "
                "row with the same address would double-fire the first citizen's schedule",
                email,
                citizen.get("path"),
                citizen.get("registry", "?"),
                seen[email],
            )
            continue

        path = Path(citizen["path"])
        seen[email] = path
        records.append(
            {
                "name": citizen.get("name", path.name),
                "email": email,
                "dir_name": path.name,
                "path": path,
                "source": _source_label(citizen, root),
            }
        )
    return records


def framework_root(repo_root: Optional[Path] = None) -> Path:
    """This install's src/aipass/ — the directory every framework citizen's branch lives in.
    Computed per call, so a patched _REPO_ROOT moves fleet and boundary together."""
    root = Path(repo_root) if repo_root is not None else _repo_root()
    return root / "src" / "aipass"


def _passport_text(passport_file: Path) -> str:
    """The text of *passport_file*, raising whatever the read raises.
    A seam so a test can inject EACCES or ENOTDIR without replacing pathlib process-wide."""
    return passport_file.read_text(encoding="utf-8")


def citizen_class_for(branch_path: Path) -> str:
    """Read citizen_class from a branch passport.

    Only a truly absent passport answers ''; any unreadable case raises PassportUnreadable.
    FileNotFoundError alone is absence: EACCES and ENOTDIR are not (Path.exists() would
    raise on the first and answer False on the second)."""
    passport_file = branch_path / ".trinity" / "passport.json"
    try:
        passport = json.loads(_passport_text(passport_file))
    except FileNotFoundError:
        return ""
    except (json.JSONDecodeError, OSError) as e:
        raise PassportUnreadable(f"passport at {passport_file} unreadable: {e}") from e

    if not isinstance(passport, dict):
        raise PassportUnreadable(f"passport at {passport_file} is not an object")

    identity = passport.get("identity", {})
    citizen_class = identity.get("citizen_class", "") if isinstance(identity, dict) else None
    if not isinstance(citizen_class, str):
        raise PassportUnreadable(f"passport at {passport_file} has no readable citizen_class")
    return citizen_class


_CLOCK_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def _time_problem(schedule: dict) -> str:
    """'' when ``time`` is absent or readable for its type ("HH:MM", or an hourly minute 0-59), else why not."""
    if "time" not in schedule:
        return ""
    raw = schedule["time"]
    sched_type = schedule.get("type")
    if sched_type in ("daily", "rotation", "weekly", "monthly"):
        match = _CLOCK_TIME.fullmatch(raw) if isinstance(raw, str) else None
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            return f'time {raw!r} is not a clock time "HH:MM"'
    elif sched_type == "hourly":
        minute = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        if isinstance(raw, str) and raw.isdigit():
            minute = int(raw)
        if minute is None or not 0 <= minute <= 59:
            return f"time {raw!r} is not a minute past the hour, 0-59"
    return ""


def _day_problem(schedule: dict) -> str:
    """'' when a weekly job names a weekday and a monthly job a day 1-31, else why not. Required, no default."""
    sched_type = schedule.get("type")
    if sched_type == "weekly" and schedule.get("weekday") not in WEEKDAYS:
        return f"weekday {schedule.get('weekday')!r} is not one of {', '.join(WEEKDAYS)}"
    if sched_type == "monthly":
        day = schedule.get("day")
        if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
            return f"day {day!r} is not a day of the month, 1-31"
    return ""


def _refused(refusals: Optional[list], message: str, *args) -> bool:
    """Log a job refusal at warning, hand its text to the caller that shows it, and answer False."""
    logger.warning(message, *args)
    if refusals is not None:
        refusals.append(message.removeprefix("[discovery] ") % args)
    return False


def _validate_job(job: dict, file_path: Path, refusals: Optional[list] = None) -> bool:
    """Validate a single job dict. Returns True if valid; a refusal's text also lands in *refusals*."""
    missing = REQUIRED_JOB_KEYS - set(job.keys())
    if missing:
        return _refused(refusals, "[discovery] Job missing keys %s in %s", missing, file_path)

    actions = [key for key in JOB_ACTION_KEYS if key in job]
    if len(actions) != 1:
        return _refused(
            refusals,
            "[discovery] Job '%s' must carry exactly one of prompt or command, found %s in %s",
            job.get("id"),
            " and ".join(actions) or "neither",
            file_path,
        )

    schedule = job.get("schedule")
    if not isinstance(schedule, dict):
        return _refused(refusals, "[discovery] Job '%s' has non-dict schedule in %s", job.get("id"), file_path)

    sched_type = schedule.get("type", "")
    if sched_type not in VALID_SCHEDULE_TYPES:
        return _refused(
            refusals, "[discovery] Job '%s' has invalid schedule type '%s' in %s", job.get("id"), sched_type, file_path
        )

    # Refused here, not in every reader: a non-number stops the whole tick, <=0 never fires,
    # NaN fails the chained bound and Infinity overflows timedelta. Absent reads as 60.
    interval = schedule.get("interval_minutes")
    if sched_type == "interval" and "interval_minutes" in schedule:
        if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 < interval < float("inf"):
            return _refused(
                refusals,
                "[discovery] Job '%s' refused in %s: interval_minutes %r is not a positive number",
                job.get("id"),
                file_path,
                interval,
            )

    problem = _time_problem(schedule) or _day_problem(schedule)
    if problem:
        return _refused(refusals, "[discovery] Job '%s' refused in %s: %s", job.get("id"), file_path, problem)

    if "command" not in job:
        wake = job.get("wake")
        if isinstance(wake, dict) and "provider" in wake and wake["provider"] not in VALID_WAKE_PROVIDERS:
            return _refused(
                refusals,
                "[discovery] Job '%s' refused in %s: wake.provider %r is not one of %s",
                job["id"],
                file_path,
                wake["provider"],
                ", ".join(VALID_WAKE_PROVIDERS),
            )
        if command_job.notify_email(job):
            logger.warning("[discovery] Job '%s' in %s: notify.email works on command jobs only", job["id"], file_path)
        return True

    problem = command_job.command_job_problem(job)
    if problem:
        return _refused(refusals, "[discovery] Command job '%s' refused in %s: %s", job.get("id"), file_path, problem)
    if "wake" in job:
        logger.warning("[discovery] Command job '%s' in %s: wake block ignored, nobody is woken", job["id"], file_path)
    return True


def _load_schedule_file(file_path: Path) -> dict:
    """Load a schedule.json file and check its shape.
    Raises OSError or ValueError (JSONDecodeError is one) when unreadable or malformed."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("the root is not an object")

    if "jobs" not in data or not isinstance(data["jobs"], list):
        raise ValueError("no 'jobs' list")

    return data


def _jobs_for_citizen(citizen: dict, skipped_owners: set, refusals: Optional[list] = None) -> List[dict]:
    """Return one citizen's validated jobs; an unreadable file or refused job adds it to *skipped_owners*."""
    daemon_dir = citizen["path"] / ".daemon"
    if not daemon_dir.is_dir():
        return []

    jobs = []
    for sched_file in sorted(daemon_dir.glob("*.json")):
        if sched_file.name.startswith("."):
            continue

        # One unreadable file skips only itself, so it cannot stop the fleet's tick.
        try:
            data = _load_schedule_file(sched_file)
        except (OSError, ValueError) as e:
            skipped_owners.add(citizen["email"])
            _refused(refusals, "[discovery] %s: not a readable schedule (%s)", sched_file, e)
            continue

        for job in data["jobs"]:
            if not isinstance(job, dict):
                skipped_owners.add(citizen["email"])
                _refused(refusals, "[discovery] A job in %s is not an object", sched_file)
                continue
            if not _validate_job(job, sched_file, refusals):
                skipped_owners.add(citizen["email"])
                continue

            entry = {
                "owner": citizen["email"],
                "id": job["id"],
                "schedule": job["schedule"],
                "wake": job.get("wake", {}),
                "enabled": job.get("enabled", True),
                "config": job.get("config", {}),
            }
            if "command" in job:
                # cwd is identity to drone; taken from the vouching record, not re-looked-up by
                # dir name, which two citizens can share across federated roots.
                entry.update(command=job["command"], branch_path=str(citizen["path"]), wake={})
                if "timeout_seconds" in job:
                    entry["timeout_seconds"] = job["timeout_seconds"]
                if "ok_exit_codes" in job:
                    entry["ok_exit_codes"] = job["ok_exit_codes"]
            else:
                entry["prompt"] = job["prompt"]
            if "notify" in job:
                entry["notify"] = job["notify"]
            jobs.append(entry)
    return jobs


def discover_jobs(skipped_owners: Optional[set] = None, refusals: Optional[list] = None) -> list:
    """Sweep every active citizen's .daemon/*.json.

    *skipped_owners* collects owners that did not read cleanly; *refusals* the text of each refused file or job.
    """
    if skipped_owners is None:
        skipped_owners = set()
    citizens = active_citizens()

    if not citizens:
        logger.warning("[discovery] No active citizens found in any registry")
        return []

    jobs = []
    for citizen in citizens:
        if citizen["dir_name"] in SKIP_DIRS or citizen["dir_name"].startswith("."):
            continue
        jobs.extend(_jobs_for_citizen(citizen, skipped_owners, refusals))

    logger.info("[discovery] Discovered %d job(s) across %d branch(es)", len(jobs), len({j["owner"] for j in jobs}))
    json_handler.log_operation("discover_jobs", {"count": len(jobs)})
    return jobs
