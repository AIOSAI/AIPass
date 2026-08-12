# =================== AIPass ====================
# Name: runstate.py
# Description: Daemon runstate tracking and due-logic for decentralized scheduler
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-08-12
# =============================================

"""
Daemon runstate — tracks last_run/next_run per job and evaluates due-ness.

Due-logic lifted verbatim from actions_registry.py (DPLAN-043), re-keyed
to composite 'owner/id' strings for the decentralized .daemon/ model.

Part of the DPLAN-0204 decentralized scheduler redesign.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler

_DAEMON_ROOT = Path(__file__).resolve().parents[3]  # src/aipass/daemon/
RUNSTATE_FILE = _DAEMON_ROOT / "daemon_json" / "daemon_runstate.json"


def _empty_runstate() -> dict:
    """Return a fresh empty runstate structure."""
    return {"version": 1, "jobs": {}}


def load_runstate() -> dict:
    """Load daemon_runstate.json. Returns empty runstate if missing."""
    if not RUNSTATE_FILE.exists():
        return _empty_runstate()
    try:
        with open(RUNSTATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "jobs" not in data:
            data["jobs"] = {}
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[runstate] Failed to load: %s", e)
        return _empty_runstate()


def save_runstate(data: dict) -> bool:
    """Save daemon_runstate.json. Returns True on success."""
    try:
        RUNSTATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(RUNSTATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        return True
    except OSError as e:
        logger.error("[runstate] Failed to save: %s", e)
        return False


def job_key(owner: str, job_id: str) -> str:
    """Build composite key for runstate lookup."""
    return f"{owner}/{job_id}"


def get_job_state(runstate: dict, owner: str, job_id: str) -> dict:
    """Get runstate entry for a job. Returns empty dict if not tracked."""
    return runstate.get("jobs", {}).get(job_key(owner, job_id), {})


# =============================================
# DUE CHECKING (lifted from actions_registry.py)
# =============================================


def _already_ran_today(last_run: Optional[str], now: datetime) -> bool:
    """Check if a daily job already ran today."""
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.date() == now.date()
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Daily last_run parse failed: %s", e)
        return False


def _already_ran_this_hour(last_run: Optional[str], now: datetime) -> bool:
    """Check if an hourly job already ran this hour."""
    if not last_run:
        return False
    try:
        last_dt = datetime.fromisoformat(last_run)
        return last_dt.hour == now.hour and last_dt.date() == now.date()
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly last_run parse failed: %s", e)
        return False


def _is_daily_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if a daily job is due (within +/-15 min window)."""
    target_time = schedule.get("time", "00:00")
    try:
        target_h, target_m = map(int, target_time.split(":"))
    except (ValueError, AttributeError) as e:
        logger.info("[runstate] Daily time parse failed for %r: %s", target_time, e)
        return False
    current_minutes = now.hour * 60 + now.minute
    target_minutes = target_h * 60 + target_m
    minutes_diff = abs(current_minutes - target_minutes)
    minutes_diff = min(minutes_diff, 1440 - minutes_diff)
    if minutes_diff > 15:
        return False
    return not _already_ran_today(last_run, now)


def _is_hourly_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if an hourly job is due (within +/-15 min window)."""
    target_m_str = schedule.get("time", "0")
    try:
        target_m = int(target_m_str)
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Hourly time parse failed for %r: %s", target_m_str, e)
        return False
    minutes_diff = abs(now.minute - target_m)
    minutes_diff = min(minutes_diff, 60 - minutes_diff)
    if minutes_diff > 15:
        return False
    return not _already_ran_this_hour(last_run, now)


def _is_interval_due(schedule: dict, last_run: Optional[str], now: datetime) -> bool:
    """Check if an interval job is due (elapsed >= interval_minutes since last_run)."""
    interval = schedule.get("interval_minutes", 60)
    if not last_run:
        return True
    try:
        last_dt = datetime.fromisoformat(last_run)
        elapsed = (now - last_dt).total_seconds() / 60
        return elapsed >= interval
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Interval last_run parse failed: %s", e)
        return True


def _is_once_due(schedule: dict, completed: Optional[str], now: datetime) -> bool:
    """Check if a one-shot job is due (due_date <= today, not completed)."""
    if completed:
        return False
    due_date = schedule.get("due_date")
    if not due_date:
        return False
    try:
        due_dt = (
            datetime.fromisoformat(due_date).date()
            if "T" in due_date
            else datetime.strptime(due_date, "%Y-%m-%d").date()
        )
        return now.date() >= due_dt
    except (ValueError, TypeError) as e:
        logger.info("[runstate] Once due_date parse failed for %r: %s", due_date, e)
        return False


def is_job_due(job: dict, runstate: dict) -> bool:
    """
    Check if a discovered job should fire now.

    Merges job schedule info with runstate tracking data.
    """
    if not job.get("enabled", True):
        return False

    state = get_job_state(runstate, job["owner"], job["id"])
    last_run = state.get("last_run")
    completed = state.get("completed")
    now = datetime.now()

    schedule = job.get("schedule", {})
    sched_type = schedule.get("type", "")

    checkers = {
        "daily": lambda: _is_daily_due(schedule, last_run, now),
        # A rotation job is a daily job that picks a different target each night.
        "rotation": lambda: _is_daily_due(schedule, last_run, now),
        "hourly": lambda: _is_hourly_due(schedule, last_run, now),
        "interval": lambda: _is_interval_due(schedule, last_run, now),
        "once": lambda: _is_once_due(schedule, completed, now),
    }

    checker = checkers.get(sched_type)
    if checker is None:
        return False
    return checker()


# =============================================
# RUNSTATE UPDATES
# =============================================


def _calc_next_run(schedule: dict, last_run_ts: str) -> Optional[str]:
    """Calculate the next run time given schedule and a last_run timestamp."""
    now = datetime.now()
    sched_type = schedule.get("type", "")

    if sched_type in ("daily", "rotation"):
        target_time = schedule.get("time", "00:00")
        try:
            target_h, target_m = map(int, target_time.split(":"))
        except (ValueError, AttributeError) as e:
            logger.info("[runstate] calc_next_run daily time parse failed: %s", e)
            return None
        next_dt = now.replace(hour=target_h, minute=target_m, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(days=1)
        return next_dt.isoformat()

    if sched_type == "hourly":
        target_m_str = schedule.get("time", "0")
        try:
            target_m = int(target_m_str)
        except (ValueError, TypeError) as e:
            logger.info("[runstate] calc_next_run hourly time parse failed: %s", e)
            return None
        next_dt = now.replace(minute=target_m, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(hours=1)
        return next_dt.isoformat()

    if sched_type == "interval":
        interval = schedule.get("interval_minutes", 60)
        try:
            last_dt = datetime.fromisoformat(last_run_ts)
            return (last_dt + timedelta(minutes=interval)).isoformat()
        except (ValueError, TypeError) as e:
            logger.info("[runstate] calc_next_run interval parse failed: %s", e)
            return now.isoformat()

    if sched_type == "once":
        return schedule.get("due_date")

    return None


def update_job_runstate(
    runstate: dict,
    owner: str,
    job_id: str,
    schedule: dict,
    timestamp: Optional[str] = None,
) -> None:
    """Update runstate for a job after successful firing."""
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = timestamp
    entry["next_run"] = _calc_next_run(schedule, timestamp)
    entry["last_status"] = "success"
    entry["last_success_at"] = timestamp
    entry["last_error"] = None

    if schedule.get("type") == "once":
        entry["completed"] = timestamp

    json_handler.log_operation("update_job_runstate", {"key": key})


def record_job_failure(
    runstate: dict,
    owner: str,
    job_id: str,
    error_msg: str,
    status: str = "failed",
    timestamp: Optional[str] = None,
) -> None:
    """Record a failed job firing in runstate."""
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    key = job_key(owner, job_id)
    entry = runstate.setdefault("jobs", {}).setdefault(key, {})
    entry["last_run"] = timestamp
    entry["last_status"] = status
    entry["last_failure_at"] = timestamp
    entry["last_error"] = error_msg[:500]

    json_handler.log_operation("record_job_failure", {"key": key, "status": status})


def prune_orphans(runstate: dict, active_keys: set) -> int:
    """Remove runstate entries for jobs that no longer exist. Returns count pruned."""
    jobs = runstate.get("jobs", {})
    orphans = set(jobs.keys()) - active_keys
    for key in orphans:
        del jobs[key]
    if orphans:
        logger.info("[runstate] Pruned %d orphan runstate entries", len(orphans))
    return len(orphans)
