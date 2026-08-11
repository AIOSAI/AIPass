# =================== AIPass ====================
# Name: discovery.py
# Description: Decentralized .daemon/ schedule file discovery
# Version: 1.0.0
# Created: 2026-06-15
# Modified: 2026-06-15
# =============================================

"""
Decentralized schedule discovery — sweeps src/aipass/*/.daemon/*.json
and returns validated Job dicts for all registered, active branches.

Part of the DPLAN-0204 decentralized scheduler redesign.
"""

import json
from pathlib import Path
from typing import Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler

_REPO_ROOT = Path(__file__).resolve().parents[6]  # up to repo root
_SRC_AIPASS = _REPO_ROOT / "src" / "aipass"
_REGISTRY_FILE = _REPO_ROOT / "AIPASS_REGISTRY.json"

SKIP_DIRS = frozenset({"compass", "__pycache__", ".git", ".venv"})

REQUIRED_JOB_KEYS = {"id", "schedule", "prompt"}
VALID_SCHEDULE_TYPES = {"daily", "hourly", "interval", "once"}


def _load_registry() -> dict:
    """Load AIPASS_REGISTRY.json. Returns empty dict on failure."""
    if not _REGISTRY_FILE.exists():
        logger.warning("[discovery] AIPASS_REGISTRY.json not found at %s", _REGISTRY_FILE)
        return {}
    try:
        with open(_REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[discovery] Failed to load registry: %s", e)
        return {}


def _build_branch_map(registry: dict) -> dict:
    """Build dir_name -> branch_email map for active, registered branches."""
    branch_map = {}
    for branch in registry.get("branches", []):
        status = branch.get("status", "")
        if status != "active":
            continue
        email = branch.get("email", "")
        path_str = branch.get("path", "")
        if not email or not path_str:
            continue
        path = Path(path_str)
        if not path.is_absolute():
            path = _REPO_ROOT / path
        if not path.exists():
            continue
        dir_name = path.name
        branch_map[dir_name] = email
    return branch_map


def active_branch_map() -> dict:
    """Return dir_name -> branch_email for every active, registered branch.

    Public entry point so sibling handlers (inbox_scanner) can resolve branch
    directories to owners without reaching into the private helpers.
    """
    return _build_branch_map(_load_registry())


def branch_path_for(dir_name: str) -> Path:
    """Return the on-disk path for a branch directory name."""
    return _SRC_AIPASS / dir_name


def _validate_job(job: dict, file_path: Path) -> bool:
    """Validate a single job dict. Returns True if valid."""
    missing = REQUIRED_JOB_KEYS - set(job.keys())
    if missing:
        logger.warning("[discovery] Job missing keys %s in %s", missing, file_path)
        return False

    schedule = job.get("schedule")
    if not isinstance(schedule, dict):
        logger.warning("[discovery] Job '%s' has non-dict schedule in %s", job.get("id"), file_path)
        return False

    sched_type = schedule.get("type", "")
    if sched_type not in VALID_SCHEDULE_TYPES:
        logger.warning(
            "[discovery] Job '%s' has invalid schedule type '%s' in %s", job.get("id"), sched_type, file_path
        )
        return False

    return True


def _load_schedule_file(file_path: Path) -> Optional[dict]:
    """Load and validate a schedule.json file. Returns parsed dict or None."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("[discovery] Failed to read %s: %s", file_path, e)
        return None

    if not isinstance(data, dict):
        logger.warning("[discovery] Non-dict root in %s", file_path)
        return None

    if "jobs" not in data or not isinstance(data["jobs"], list):
        logger.warning("[discovery] Missing or invalid 'jobs' array in %s", file_path)
        return None

    return data


def discover_jobs() -> list:
    """
    Sweep src/aipass/*/.daemon/*.json and return validated Job dicts.

    Each Job dict: {owner, id, schedule, wake, prompt, enabled}
    Only returns jobs from registered, active branches.
    """
    branch_map = active_branch_map()

    if not branch_map:
        logger.warning("[discovery] No active branches found in registry")
        return []

    jobs = []

    for branch_dir in sorted(_SRC_AIPASS.iterdir()):
        if not branch_dir.is_dir():
            continue
        if branch_dir.name in SKIP_DIRS:
            continue
        if branch_dir.name.startswith("."):
            continue

        owner_email = branch_map.get(branch_dir.name)
        if not owner_email:
            continue

        daemon_dir = branch_dir / ".daemon"
        if not daemon_dir.is_dir():
            continue

        for sched_file in sorted(daemon_dir.glob("*.json")):
            if sched_file.name.startswith("."):
                continue

            data = _load_schedule_file(sched_file)
            if data is None:
                continue

            for job in data["jobs"]:
                if not _validate_job(job, sched_file):
                    continue

                jobs.append(
                    {
                        "owner": owner_email,
                        "id": job["id"],
                        "schedule": job["schedule"],
                        "wake": job.get("wake", {}),
                        "prompt": job["prompt"],
                        "enabled": job.get("enabled", True),
                    }
                )

    logger.info("[discovery] Discovered %d job(s) across %d branch(es)", len(jobs), len({j["owner"] for j in jobs}))
    json_handler.log_operation("discover_jobs", {"count": len(jobs)})
    return jobs
