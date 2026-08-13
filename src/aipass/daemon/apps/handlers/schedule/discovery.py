# =================== AIPass ====================
# Name: discovery.py
# Description: Decentralized .daemon/ schedule file discovery
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-08-12
# =============================================

"""
Decentralized schedule discovery — sweeps every active citizen's .daemon/*.json
and returns validated Job dicts.

Two trees are scanned (DPLAN-0287 piece 2):
  - src/aipass/*        — framework citizens, listed in AIPASS_REGISTRY.json
  - projects/<name>/*   — project citizens, listed in that project's own sealed
                          <NAME>_REGISTRY.json

Part of the DPLAN-0204 decentralized scheduler redesign.
"""

import json
from pathlib import Path
from typing import List, Optional

from aipass.prax import logger
from aipass.daemon.apps.handlers.json import json_handler

_REPO_ROOT = Path(__file__).resolve().parents[6]  # up to repo root
_SRC_AIPASS = _REPO_ROOT / "src" / "aipass"
_REGISTRY_FILE = _REPO_ROOT / "AIPASS_REGISTRY.json"
_PROJECTS_DIR_NAME = "projects"

SKIP_DIRS = frozenset({"compass", "__pycache__", ".git", ".venv"})

REQUIRED_JOB_KEYS = {"id", "schedule", "prompt"}
VALID_SCHEDULE_TYPES = {"daily", "hourly", "interval", "once", "rotation"}

# Source labels on a citizen record — which registry vouched for it.
SOURCE_AIPASS = "aipass"

# Passport citizen_class that reads its mail live and must never be woken into
# an interactive session by a scheduled job.
MANAGER_CLASS = "manager"


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


def _citizen_records(registry: dict, base: Path, source: str) -> List[dict]:
    """Build citizen records for one registry, resolving paths against `base`.

    `base` is the root a relative registry path is measured from: the repo root
    for AIPASS_REGISTRY.json, the project root for a sealed project registry.
    Project paths must NOT fall back to the repo root — 'src/baud/baud' happens
    to exist in both trees, and resolving it repo-first picks the wrong one.
    """
    records = []
    for branch in registry.get("branches", []):
        if branch.get("status", "") != "active":
            continue
        email = branch.get("email", "")
        path_str = branch.get("path", "")
        if not email or not path_str:
            continue
        path = Path(path_str)
        if not path.is_absolute():
            path = base / path
        if not path.exists():
            continue
        records.append(
            {
                "name": branch.get("name", path.name),
                "email": email,
                "dir_name": path.name,
                "path": path,
                "source": source,
            }
        )
    return records


def _project_registry_files() -> List[Path]:
    """Return every sealed project registry file, in project-name order."""
    projects_dir = _REPO_ROOT / _PROJECTS_DIR_NAME
    if not projects_dir.is_dir():
        return []

    files = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir() or project_dir.name in SKIP_DIRS:
            continue
        files.extend(sorted(project_dir.glob("*_REGISTRY.json")))
    return files


def _load_registry_file(path: Path) -> dict:
    """Load one registry JSON file. Returns empty dict on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[discovery] Failed to load registry %s: %s", path, e)
        return {}


def active_citizens() -> List[dict]:
    """Return an ordered record per active citizen across both trees.

    Record: {name, email, dir_name, path, source}. Framework citizens come
    first in AIPASS_REGISTRY.json order, then project citizens in project-name
    order — this ordering is the steward rotation's roster order.
    """
    citizens = _citizen_records(_load_registry(), _REPO_ROOT, SOURCE_AIPASS)

    for registry_file in _project_registry_files():
        project_root = registry_file.parent
        source = f"{_PROJECTS_DIR_NAME}/{project_root.name}"
        citizens.extend(_citizen_records(_load_registry_file(registry_file), project_root, source))

    seen = set()
    unique = []
    for citizen in citizens:
        if citizen["email"] in seen:
            logger.info("[discovery] Duplicate citizen %s ignored (%s)", citizen["email"], citizen["source"])
            continue
        seen.add(citizen["email"])
        unique.append(citizen)
    return unique


def active_branch_map() -> dict:
    """Return dir_name -> branch_email for every active, registered citizen.

    Public entry point so sibling handlers (inbox_scanner) can resolve branch
    directories to owners without reaching into the private helpers.
    """
    return {c["dir_name"]: c["email"] for c in active_citizens()}


def branch_path_for(dir_name: str) -> Path:
    """Return the on-disk path for a branch directory name.

    Resolved from the citizen records so project citizens land in their own
    tree; falls back to src/aipass/<dir_name> for anything unregistered.
    """
    for citizen in active_citizens():
        if citizen["dir_name"] == dir_name:
            return citizen["path"]
    return _SRC_AIPASS / dir_name


def citizen_class_for(branch_path: Path) -> str:
    """Read citizen_class from a branch passport. Returns '' when unreadable."""
    passport_file = branch_path / ".trinity" / "passport.json"
    try:
        with open(passport_file, "r", encoding="utf-8") as f:
            passport = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as e:
        logger.info("[discovery] Could not read passport at %s: %s", passport_file, e)
        return ""

    if not isinstance(passport, dict):
        logger.info("[discovery] Non-dict passport at %s", passport_file)
        return ""

    return passport.get("identity", {}).get("citizen_class", "")


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


def _jobs_for_citizen(citizen: dict) -> List[dict]:
    """Read one citizen's .daemon/*.json files and return its validated jobs."""
    daemon_dir = citizen["path"] / ".daemon"
    if not daemon_dir.is_dir():
        return []

    jobs = []
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
                    "owner": citizen["email"],
                    "id": job["id"],
                    "schedule": job["schedule"],
                    "wake": job.get("wake", {}),
                    "prompt": job["prompt"],
                    "enabled": job.get("enabled", True),
                    "config": job.get("config", {}),
                }
            )
    return jobs


def discover_jobs() -> list:
    """
    Sweep every active citizen's .daemon/*.json and return validated Job dicts.

    Each Job dict: {owner, id, schedule, wake, prompt, enabled, config}
    Covers both src/aipass/* and projects/*/ citizens.
    """
    citizens = active_citizens()

    if not citizens:
        logger.warning("[discovery] No active citizens found in any registry")
        return []

    jobs = []
    for citizen in citizens:
        if citizen["dir_name"] in SKIP_DIRS or citizen["dir_name"].startswith("."):
            continue
        jobs.extend(_jobs_for_citizen(citizen))

    logger.info("[discovery] Discovered %d job(s) across %d branch(es)", len(jobs), len({j["owner"] for j in jobs}))
    json_handler.log_operation("discover_jobs", {"count": len(jobs)})
    return jobs
