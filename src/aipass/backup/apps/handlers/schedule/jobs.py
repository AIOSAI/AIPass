# =================== AIPass ====================
# Name: jobs.py
# Description: Scheduled backups — one @daemon command job per registered project in .daemon/schedule.json
# Version: 1.1.0
# Created: 2026-11-15
# Modified: 2026-11-15
# =============================================

"""Scheduled backup jobs: one @daemon command job per project, in the file @daemon already reads.

Reference: docs/schedule.md
"""

import re
from pathlib import Path

from ..audit import trail
from ..json import json_handler

SCHEDULE_PATH = Path(__file__).resolve().parents[3] / ".daemon" / "schedule.json"
JOB_PREFIX = "backup-"
#: The owner's 8 h for a Drive upload of a whole snapshot store; a snapshot alone ends far sooner.
TIMEOUT_SECONDS = 28800
NOTIFY_EMAIL = "@devpulse"
NOTE = (
    "Scheduled backup of one registered project: the all lane, snapshot then Drive when the "
    "project's drive_sync is on. Written by 'drone @backup schedule'; set it there. Reference: docs/schedule.md"
)
_TIME = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_DAY = re.compile(r"[1-9]|[12]\d|3[01]")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
#: Each set form's words after the frequency, in @daemon's field names.
SHAPES = {"daily": ("time",), "weekly": ("weekday", "time"), "monthly": ("day", "time")}


class ScheduleError(Exception):
    """The schedule file or a job in it cannot be read or written as this handler writes it."""


def job_id(name: str) -> str:
    """The @daemon job id of a project's scheduled backup."""
    return f"{JOB_PREFIX}{name}"


def valid_time(value: object) -> bool:
    """True for a 24-hour HH:MM, the form @daemon's windowed types take."""
    return isinstance(value, str) and _TIME.fullmatch(value) is not None


def _valid(schedule: object) -> bool:
    """True for a daily, weekly or monthly @daemon schedule with every field in range."""
    if not isinstance(schedule, dict) or not valid_time(schedule.get("time")):
        return False
    kind = schedule.get("type")
    day = schedule.get("day")
    return (
        kind == "daily"
        or (kind == "weekly" and schedule.get("weekday") in WEEKDAYS)
        or (kind == "monthly" and type(day) is int and 1 <= day <= 31)
    )


def schedule_from(words: list[str]) -> dict:
    """@daemon's schedule for one set form: daily HH:MM | weekly WEEKDAY HH:MM | monthly DAY HH:MM."""
    kind, *rest = words
    if kind not in SHAPES or len(rest) != len(SHAPES[kind]):
        raise ScheduleError(f"schedule does not take: {' '.join(words)}")
    schedule: dict = {"type": kind, **dict(zip(SHAPES[kind], rest))}
    if kind == "monthly" and _DAY.fullmatch(schedule["day"]):
        schedule["day"] = int(schedule["day"])
    if not _valid(schedule):
        raise ScheduleError(
            f"Not a {kind} schedule: {' '.join(rest)} (weekday monday..sunday, day 1-31, time 24-hour HH:MM)"
        )
    return schedule


def _read() -> dict:
    """The schedule document; ScheduleError when it is unreadable or has no jobs list."""
    data = json_handler.read_json(SCHEDULE_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ScheduleError(f"Schedule file unreadable or without a jobs list: {SCHEDULE_PATH}")
    return data


def find_job(name: str) -> dict | None:
    """The project's job, or None when it has no schedule."""
    return next((job for job in _read()["jobs"] if job.get("id") == job_id(name)), None)


def parse_job(job: dict) -> dict:
    """on, frequency, time, weekday and day from a job this handler wrote; ScheduleError on any other shape."""
    schedule = job.get("schedule")
    if not isinstance(schedule, dict) or not _valid(schedule):
        raise ScheduleError(f"Job {job.get('id')} has a schedule this verb does not write: {schedule}")
    return {
        "on": job.get("enabled") is True,
        "frequency": schedule["type"],
        "time": schedule["time"],
        "weekday": schedule["weekday"] if schedule["type"] == "weekly" else None,
        "day": schedule["day"] if schedule["type"] == "monthly" else None,
    }


def write_job(name: str, on: bool | None = None, schedule: dict | None = None) -> dict:
    """Set a project's schedule (from ``schedule_from``) or turn it on or off; the other is kept.

    A new job starts off: turning a backup on is its own word, never a side effect of a time.
    """
    if schedule is not None and not _valid(schedule):
        raise ScheduleError(f"Not a schedule this verb writes: {schedule}")
    data = _read()
    job = next((j for j in data["jobs"] if j.get("id") == job_id(name)), None)
    if job is None:
        if schedule is None:
            raise ScheduleError(f"No schedule for {name} yet: set one first (daily, weekly or monthly)")
        job = {
            "id": job_id(name),
            "enabled": False,
            "schedule": {},
            "command": f"drone @backup all @{name} --quiet",
            "timeout_seconds": TIMEOUT_SECONDS,
            "notify": {"email": NOTIFY_EMAIL},
            "_note": NOTE,
        }
        data["jobs"].append(job)
    if schedule is not None:
        job["schedule"] = schedule
    if on is not None:
        job["enabled"] = on
    if not json_handler.write_json(SCHEDULE_PATH, data):
        raise ScheduleError(f"Could not write {SCHEDULE_PATH}")
    trail.log_operation("schedule_written", {"job": job["id"], "enabled": job["enabled"], "schedule": job["schedule"]})
    return job


def remove_job(name: str) -> bool:
    """Remove the project's job; False when it had none. ScheduleError when the file cannot be read or written."""
    data = _read()
    kept = [job for job in data["jobs"] if job.get("id") != job_id(name)]
    if len(kept) == len(data["jobs"]):
        return False
    data["jobs"] = kept
    if not json_handler.write_json(SCHEDULE_PATH, data):
        raise ScheduleError(f"Could not write {SCHEDULE_PATH}")
    trail.log_operation("schedule_removed", {"job": job_id(name)})
    return True
