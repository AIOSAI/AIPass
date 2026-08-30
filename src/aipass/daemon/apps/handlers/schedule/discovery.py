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

# @memory's PUBLIC gateway to the fleet definition (apps/modules/fleet.py,
# built on our dispatch 2a70bbcd): handlers/ is private implementation, and
# importing it cross-branch failed encapsulation + handlers on the checklist.
from aipass.memory.apps.modules import fleet as registry_scope

_REPO_ROOT = Path(__file__).resolve().parents[6]  # up to repo root
_SRC_AIPASS = _REPO_ROOT / "src" / "aipass"
_REGISTRY_FILE = _REPO_ROOT / "AIPASS_REGISTRY.json"
_PROJECTS_DIR_NAME = "projects"

# Candidate discovery: exactly one level under projects/, dot-prefixed
# components refused by the explicit filter in _project_registry_files().
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"

SKIP_DIRS = frozenset({"compass", "__pycache__", ".git", ".venv"})

PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

# The values passport 2.0 defines for citizenship.residency. Re-exported from
# @memory rather than re-spelled: two copies of a vocabulary drift silently.
RESIDENCY_CORE = registry_scope.RESIDENCY_CORE
RESIDENCY_RESIDENT = registry_scope.RESIDENCY_RESIDENT

REQUIRED_JOB_KEYS = {"id", "schedule", "prompt"}
VALID_SCHEDULE_TYPES = {"daily", "hourly", "interval", "once", "rotation"}

# Source labels on a citizen record — which registry vouched for it.
SOURCE_AIPASS = "aipass"
SOURCE_EXTERNAL = "external"

# The core registry's file name, as @memory's records spell it.
_CORE_REGISTRY_NAME = "AIPASS_REGISTRY.json"

# Passport citizen_class that reads its mail live and must never be woken into
# an interactive session by a scheduled job.
MANAGER_CLASS = "manager"


def declared_residency(branch_path: Path) -> Optional[str]:
    """What the passport at *branch_path* declares itself to be.

    Delegates to :mod:`registry_scope`, which owns the field. Kept as a name
    here because callers and tests in this branch import it from discovery,
    and because re-spelling the read is exactly the duplication 2.1.0 removes.
    """
    return registry_scope.declared_residency(branch_path)


def _source_label(record: dict, repo_root: Path) -> str:
    """A human label for WHICH registry vouched for this citizen.

    Presentation only — nothing routes on it. It is printed by
    ``drone @daemon rotation`` and carried in the rotation's JSON, so the
    strings are a display contract rather than a policy one.

    @memory's record carries the registry FILE NAME, which is enough to tell
    core from everything else but not enough to name the project. The project
    directory is recovered from the citizen's own path, one level under
    ``projects/``. A citizen outside both trees is labelled by its registry
    stem, so the federated externals land as ``external/WREN`` rather than
    silently reading as core.
    """
    if record.get("registry") == _CORE_REGISTRY_NAME:
        return SOURCE_AIPASS

    path = Path(record["path"])
    projects_dir = repo_root / _PROJECTS_DIR_NAME

    # Asked rather than caught: a citizen outside projects/ is the ORDINARY
    # federated-external case, not an exception, and catching ValueError here
    # would read as error handling for something that is simply a third tier.
    if not path.is_relative_to(projects_dir):
        stem = str(record.get("registry", "")).replace("_REGISTRY.json", "")
        return f"{SOURCE_EXTERNAL}/{stem}" if stem else SOURCE_EXTERNAL

    return f"{_PROJECTS_DIR_NAME}/{path.relative_to(projects_dir).parts[0]}"


def active_citizens(repo_root: Optional[Path] = None) -> List[dict]:
    """Return an ordered record per active citizen, in @memory's fleet order.

    Record: {name, email, dir_name, path, source}.

    WHO COUNTS IS NOT DECIDED HERE ANY MORE (FPLAN-0460). The core-registry
    read, the ``projects/*`` glob, the dot-filter and the two-key resident
    rule all used to live in this module in a second copy. They are now one
    call to :func:`registry_scope.fleet_branches`, because a fleet definition
    with two implementations agrees only by coincidence — and the day the
    federated-external anchor lands in the core registry, this lane gains
    those citizens without a line changing here. That is the whole point of
    consuming rather than mirroring.

    WHAT IS STILL DECIDED HERE is the one thing @memory deliberately left to
    each caller: an address. Their ruling is that a branch with no ``email``
    is KEPT, because the path-based lanes (trinity push, rollover) still want
    it. Daemon cannot use it — a job's owner IS an email and the wake targets
    an email — so it is refused, and refused LOUDLY at error level. A citizen
    dropped without a line in the log is indistinguishable from one that was
    never discovered.

    Args:
        repo_root: Root to resolve the fleet against; defaults to this
            checkout's. Threaded through so a test can drive a temp tree
            without patching module state.

    Returns:
        One record per addressable active citizen, fleet order preserved.
    """
    # Defaults to the module constant rather than passing None straight through,
    # so patching _REPO_ROOT still redirects the whole lane — the seam every
    # temp-tree test in this branch already drives.
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT

    # @memory deduplicates by resolved PATH — correct for their lanes, which are
    # path-keyed. Daemon is email-keyed: a job's owner IS an address and the wake
    # targets one, so two rows sharing an email are ambiguous here even when they
    # name different directories. Deduplicated on daemon's own axis, and named.
    records = []
    seen: dict = {}
    for citizen in registry_scope.fleet_branches(root, name_from="registry"):
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


def active_branch_map(repo_root: Optional[Path] = None) -> dict:
    """Return dir_name -> branch_email for every active, registered citizen.

    Public entry point so sibling handlers (inbox_scanner) can resolve branch
    directories to owners without reaching into the private helpers.
    """
    return {c["dir_name"]: c["email"] for c in active_citizens(repo_root)}


def branch_path_for(dir_name: str, repo_root: Optional[Path] = None) -> Path:
    """Return the on-disk path for a branch directory name.

    Resolved from the citizen records so project citizens land in their own
    tree; falls back to src/aipass/<dir_name> for anything unregistered.
    """
    for citizen in active_citizens(repo_root):
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
