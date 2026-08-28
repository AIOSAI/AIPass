# =================== AIPass ====================
# Name: discovery.py
# Description: Decentralized .daemon/ schedule file discovery
# Version: 2.0.0
# Created: 2026-06-15
# Modified: 2026-08-28
# =============================================

"""
Decentralized schedule discovery — sweeps every active citizen's .daemon/*.json
and returns validated Job dicts.

Two trees are scanned (DPLAN-0287 piece 2):
  - src/aipass/*        — framework citizens, listed in AIPASS_REGISTRY.json
  - projects/<name>/    — project citizens, listed in that project's own sealed
                          <NAME>_REGISTRY.json

WHO COUNTS AS A CITIZEN (2.0.0, DPLAN-0319 wave 3)
--------------------------------------------------
This module decides who the scheduler fires for, who the steward rotation
walks, and whose inbox the sweep looks in. It now answers that question the
same way @memory's registry_scope and @ai_mail's registry/read.py answer it,
because a fleet definition with three implementations agrees only by
coincidence.

DISCOVERY IS REGISTRY-LED AND SHALLOW. Candidates are exactly
``projects/<project>/<NAME>_REGISTRY.json``, one level down, with every
dot-prefixed path component refused by an explicit filter — ``pathlib`` globs
match hidden directories where a shell would not, so without that line
``projects/.archive/`` walks straight back in. Before this version the walk
reached it: ``SKIP_DIRS`` never listed ``.archive``, and a registry planted
directly inside it WAS discovered (verified on a temp tree, ``@ghost``
resolved). The parked projects escaped only because they sit one level deeper
than the walk reached — excluded by an accident of depth, not by a rule.

DISCOVERY NEVER WALKS PASSPORTS, and the distinction is load-bearing rather
than stylistic: on this machine a passport walk under ``projects/`` returns
EIGHT passports for FOUR residents, because ``baud`` carries real
resident-declaring passports under ``.backup/versioned/`` and
``.backup/snapshots/``. A backup copy of a declaration is still a declaration.
Reading a passport only at a path some registry declared is what makes the
count right.

CLASSIFICATION READS THE BRANCH'S OWN PASSPORT — ``citizenship.residency`` via
:func:`declared_residency`. Inside ``projects/`` BOTH keys are required: the
registry lists the branch active AND the passport declares ``resident``. Every
other outcome is refused and NAMED through :func:`_refuse_resident` — missing
passport, unreadable passport, absent field, ``core`` claimed from inside
``projects/``, an unknown value, or a registry path that is not on disk. A
candidate refused without a line in the log is indistinguishable from one that
was never discovered, and those two need very different fixes.

THE TRUST MODEL is asymmetric on purpose. A passport can never ADD scope —
nothing walks passports, so a declared resident no discovered registry lists is
unreachable by construction. A passport can never REMOVE a core citizen — a
core branch that declares nothing is KEPT and the disagreement is logged,
because if an absent field could drop a citizen, an agent could stop its own
jobs firing by deleting one line of its own file.

POLICY CHANGE, stated plainly. The old walk made every branch a projects
registry marked ``active`` into a citizen, so a parked project kept its place
in the scheduler, the rotation and the sweep on the strength of a status field
nobody had revisited — ``marketstand`` is parked and its registry still says
``active``. The passport is now the second key and such a project is refused.
On this machine the live roster is unchanged (22 citizens: 18 core + 4
residents, all four declaring ``resident``), because both parked projects
already sat under ``projects/.archive/``; the change bites the day one is
parked in place rather than moved.

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

# Candidate discovery: exactly one level under projects/, dot-prefixed
# components refused by the explicit filter in _project_registry_files().
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"

SKIP_DIRS = frozenset({"compass", "__pycache__", ".git", ".venv"})

PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

# The two values passport 2.0 defines for citizenship.residency.
RESIDENCY_CORE = "core"
RESIDENCY_RESIDENT = "resident"

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


def declared_residency(branch_path: Path) -> Optional[str]:
    """What the passport at *branch_path* declares itself to be.

    The single reader for ``citizenship.residency`` on this branch. Every lane
    that needs to know whether a branch is core or resident goes through here,
    so the field is spelled once.

    An absent or unreadable passport declares NOTHING and does not raise. The
    caller decides what silence means: for a core citizen it means "log it and
    keep them", for a resident candidate it means "refuse". Returning None for
    both is what lets one reader serve two policies.

    Args:
        branch_path: Branch directory holding ``.trinity/passport.json``.

    Returns:
        The declared residency string, or None when nothing is declared.
    """
    passport = Path(branch_path) / PASSPORT_RELATIVE
    try:
        data = json.loads(passport.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug("[discovery] No passport at %s — declares nothing", passport)
        return None
    except (OSError, ValueError, UnicodeDecodeError) as e:
        logger.error("[discovery] Unreadable passport %s: %s", passport, e)
        return None

    if not isinstance(data, dict):
        logger.error("[discovery] Non-dict passport at %s — declares nothing", passport)
        return None

    residency = data.get("citizenship", {}).get("residency")
    return residency if isinstance(residency, str) else None


def _refuse_resident(name: str, path: Path, registry_path: Path, reason: str) -> None:
    """Log a refused resident candidate by name, path and reason.

    Every rejection funnels through here so none can be silent. A candidate
    refused without a line in the log looks exactly like one that was never
    discovered, and a parked project and a broken glob need different fixes.
    """
    logger.error(
        "[discovery] REFUSED resident '%s' at %s (listed active in %s): %s",
        name,
        path,
        registry_path.name,
        reason,
    )


def _classify_resident(name: str, path: Path, registry_path: Path) -> bool:
    """Decide one resident candidate on its own passport, naming any refusal.

    Split out from the record loop so the decision can be read — and changed —
    without the iteration that surrounds it.
    """
    residency = declared_residency(path)
    if residency == RESIDENCY_RESIDENT:
        return True

    if residency is None:
        reason = "passport declares no residency (missing, unreadable, or no field)"
    elif residency == RESIDENCY_CORE:
        reason = f"passport declares '{RESIDENCY_CORE}' from inside {_PROJECTS_DIR_NAME}/"
    else:
        reason = f"passport declares unknown residency '{residency}'"
    _refuse_resident(name, path, registry_path, reason)
    return False


def _citizen_records(registry: dict, base: Path, source: str, resident_registry: Optional[Path] = None) -> List[dict]:
    """Build citizen records for one registry, resolving paths against `base`.

    `base` is the root a relative registry path is measured from: the repo root
    for AIPASS_REGISTRY.json, the project root for a sealed project registry.
    Project paths must NOT fall back to the repo root — 'src/baud/baud' happens
    to exist in both trees, and resolving it repo-first picks the wrong one.

    Args:
        registry: The parsed registry document.
        base: Root that relative branch paths are resolved against.
        source: Label recorded on each record — which registry vouched for it.
        resident_registry: Set to the registry FILE when these rows are resident
            candidates: each then also needs a passport declaring ``resident``,
            and every refusal is named against this file. Left None for the
            sealed core registry, whose citizens are included unconditionally.

    Returns:
        One record per accepted branch: {name, email, dir_name, path, source}.
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
        name = branch.get("name", path.name)
        if not path.exists():
            if resident_registry is not None:
                _refuse_resident(name, path, resident_registry, "registry path does not exist on disk")
            continue
        if resident_registry is not None and not _classify_resident(name, path, resident_registry):
            continue
        records.append(
            {
                "name": name,
                "email": email,
                "dir_name": path.name,
                "path": path,
                "source": source,
            }
        )
    return records


def _project_registry_files() -> List[Path]:
    """Candidate resident-project registries. DISCOVERY ONLY — decides nothing.

    Registry-led and shallow, and both halves are load-bearing. Exactly one
    level under ``projects/``, so a registry nested deeper is out of reach; and
    every dot-prefixed component refused by the explicit filter below, because
    ``pathlib`` globs match hidden directories where a shell would not. On the
    live tree the parked projects are excluded by BOTH, which is why each layer
    is pinned alone — either one looks unnecessary until the other is removed.

    A checkout with no ``projects/`` returns empty and does not raise: CI runs
    on exactly that tree, since ``projects/`` is gitignored.

    Returns:
        Absolute registry paths, sorted, one per candidate project.
    """
    projects_dir = _REPO_ROOT / _PROJECTS_DIR_NAME
    if not projects_dir.is_dir():
        return []

    files = []
    for path in sorted(projects_dir.glob(RESIDENT_REGISTRY_GLOB)):
        if any(part.startswith(".") for part in path.relative_to(projects_dir).parts):
            continue
        files.append(path)
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

    Record: {name, email, dir_name, path, source}. Core citizens come first in
    AIPASS_REGISTRY.json order, then residents in project-name order — this
    ordering is the steward rotation's roster order.

    The two halves are judged by DIFFERENT rules on purpose. Core citizens come
    from the sealed registry and are included unconditionally; one that declares
    something other than 'core' is logged and KEPT, because an agent-writable
    field must never be able to remove its own branch from the scheduler.
    Resident candidates need both keys — see :func:`_classify_resident` — since
    there the passport is the only thing separating a live project from a
    parked one.
    """
    citizens = _citizen_records(_load_registry(), _REPO_ROOT, SOURCE_AIPASS)
    for citizen in citizens:
        residency = declared_residency(citizen["path"])
        if residency != RESIDENCY_CORE:
            logger.warning(
                "[discovery] Core citizen %s declares residency %r, not '%s' — kept, "
                "because the sealed registry is the anchor",
                citizen["email"],
                residency,
                RESIDENCY_CORE,
            )

    for registry_file in _project_registry_files():
        project_root = registry_file.parent
        source = f"{_PROJECTS_DIR_NAME}/{project_root.name}"
        citizens.extend(
            _citizen_records(_load_registry_file(registry_file), project_root, source, resident_registry=registry_file)
        )

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
