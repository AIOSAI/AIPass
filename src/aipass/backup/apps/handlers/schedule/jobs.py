# =================== AIPass ====================
# Name: jobs.py
# Description: Scheduled backups — one @daemon command job per registered project in .daemon/schedule.json
# Version: 1.0.0
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


class ScheduleError(Exception):
    """The schedule file or a job in it cannot be read or written as this handler writes it."""


def job_id(name: str) -> str:
    """The @daemon job id of a project's scheduled backup."""
    return f"{JOB_PREFIX}{name}"


def valid_time(value: object) -> bool:
    """True for a 24-hour HH:MM, the form @daemon's daily type takes."""
    return isinstance(value, str) and _TIME.fullmatch(value) is not None


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
    """on, frequency and time from a job this handler wrote; ScheduleError on any other shape."""
    schedule = job.get("schedule")
    if not isinstance(schedule, dict) or schedule.get("type") != "daily" or not valid_time(schedule.get("time")):
        raise ScheduleError(f"Job {job.get('id')} has a schedule this verb does not write: {schedule}")
    return {
        "on": job.get("enabled") is True,
        "frequency": "daily",
        "time": schedule["time"],
        "weekday": None,
        "day": None,
    }


def write_job(name: str, on: bool | None = None, time: str | None = None) -> dict:
    """Set a project's schedule: ``time`` makes it daily at that time, ``on`` turns it on or off.

    A new job starts off: turning a backup on is its own word, never a side effect of a time.
    """
    if time is not None and not valid_time(time):
        raise ScheduleError(f"Not a 24-hour HH:MM time: {time}")
    data = _read()
    job = next((j for j in data["jobs"] if j.get("id") == job_id(name)), None)
    if job is None:
        if time is None:
            raise ScheduleError(f"No schedule for {name} yet: set a time first (daily HH:MM)")
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
    if time is not None:
        job["schedule"] = {"type": "daily", "time": time}
    if on is not None:
        job["enabled"] = on
    if not json_handler.write_json(SCHEDULE_PATH, data):
        raise ScheduleError(f"Could not write {SCHEDULE_PATH}")
    trail.log_operation("schedule_written", {"job": job["id"], "enabled": job["enabled"], "schedule": job["schedule"]})
    return job
