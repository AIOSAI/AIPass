# =================== AIPass ====================
# Name: registry_scope.py
# Description: The one definition of "the fleet" — core citizens plus passport-declared residents
# Version: 2.0.0
# Created: 2026-08-27
# Modified: 2026-08-28
# =============================================

"""Fleet Scope

Which branches @memory's lanes are responsible for, defined once.

Before this module the answer differed per lane.  The trinity push resolved
its own scope from a named constant and reached all 22 branches; every other
lane — rollover, lint, health — walked ``detector._read_registry()`` and
reached 19, because it only knew the core registry plus whatever external
registry a caller's cwd happened to have persisted into
``known_registries.json``.  ``baud`` was in that file by accident of where
somebody once stood; ``earmark``, ``finch`` and ``aipass_site`` were not, and
so three citizens' memory files could overflow with no rollover ever running
on them.  A gap that depends on a caller's working directory is not a policy.

DECLARED IN A PASSPORT, ANCHORED IN A REGISTRY (2.0.0, DPLAN-0319)
------------------------------------------------------------------
Passport 2.0 gives every citizen ``citizenship.residency`` — ``core`` or
``resident``.  Classification now reads that field instead of a named
4-tuple.  Discovery still globs, but it globs REGISTRIES, never passports,
and the distinction is load-bearing rather than stylistic: a passport walk
under ``projects/`` on this machine returns EIGHT passports for FOUR
residents, because ``baud`` carries two more under ``.backup/versioned/`` and
``.backup/snapshots/``, each a real passport declaring ``residency:
resident``.  A backup copy of a declaration is still a declaration.  Reading
a passport only at a path some registry declared is what makes the count
right.

THE TRUST MODEL decides who wins when the two disagree.  A passport is
agent-writable; a registry is not.  So:

* A passport can never ADD scope.  Nothing walks passports, so a declared
  resident that no discovered registry lists is unreachable by construction —
  refused by never being looked at, not by being filtered out later.
* A passport can never REMOVE a core citizen.  A core branch declaring
  nothing stays in the fleet and the disagreement is logged.  If an absent
  field could drop a citizen, an agent could stop its own memories being
  rolled over by deleting one line of its own file.
* Inside ``projects/``, both keys are required: the project registry lists the
  branch active AND the passport declares ``resident``.  Every other outcome is
  refused and NAMED — missing passport, unreadable passport, absent field,
  ``core`` claimed from inside ``projects/``, or a value nobody defined.

WHAT REPLACED THE NAMED LIST'S FRICTION, stated plainly because it is weaker
in one specific way.  The old constant meant adding a resident required an
edit here.  Now a directory under ``projects/`` carrying a registry and a
passport that declares ``resident`` joins the fleet on its own.  The friction
did not vanish, it moved: the declaration is a deliberate write to a tracked
passport.  It is genuinely less friction than a review of this file, and that
trade is the ruling, not an oversight.

THE STALE-CITIZEN RULE, which the named list used to carry alone.
``marketstand`` is parked but its registry still marks its branch ``active``,
so a status field can never be trusted by itself.  It is excluded three deep,
and each layer alone suffices: it lives under ``projects/.archive/`` and every
dot-prefixed path component is refused; its registry sits below the one-level
discovery depth; and its passport declares no residency at all.  Removing any
one layer must not quietly open the door, which is why the tests assert them
one at a time.

Discovery of registries OUTSIDE the repo (an external project whose agent
calls in from its own tree) is a separate mechanism and is untouched by this
module — see ``detector._find_caller_registries``.
"""

import json
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

CORE_REGISTRY = "AIPASS_REGISTRY.json"

# Discovery: exactly one level under this directory, dot-prefixed components
# refused. Named so other branches can mirror the rule without importing it.
RESIDENT_PROJECTS_DIR = "projects"
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"
PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

# The two values passport 2.0 defines for citizenship.residency.
RESIDENCY_CORE = "core"
RESIDENCY_RESIDENT = "resident"

# DEMOTED 2026-08-28: this was the classifier, it is now only a drift anchor.
# Nothing is included or excluded on the strength of this tuple — it is compared
# against what discovery actually found and a disagreement is logged. It
# survives this wave because @ai_mail's cross-project bridge AST-parses this
# very assignment to pin its own mirror; deleting it here turns another
# citizen's suite red for a reason that has nothing to do with them. Delete it
# the moment @ai_mail lands the same semantics.
RESIDENT_REGISTRIES = (
    "projects/baud/BAUD_REGISTRY.json",
    "projects/earmark/EARMARK_REGISTRY.json",
    "projects/finch/FINCH_REGISTRY.json",
    "projects/aipass-site/AIPASS-SITE_REGISTRY.json",
)


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* to the directory holding ``AIPASS_REGISTRY.json``."""
    current = Path(start) if start is not None else Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / CORE_REGISTRY).exists():
            return parent
    return Path.cwd()


REPO_ROOT = find_repo_root()


def declared_residency(branch_path: Path) -> str | None:
    """What the passport at *branch_path* declares itself to be.

    The single reader for ``citizenship.residency``.  Every lane that needs to
    know whether a branch is core or resident should go through here rather
    than reach into the passport itself, so the field is only spelled once.

    An absent or unreadable passport declares NOTHING and does not raise.  A
    branch cannot be punished for a file the caller failed to hand it, and the
    caller — not this function — decides what silence means: for a core
    citizen it means "log it and keep them", for a resident candidate it means
    "refuse".  Returning ``None`` for both cases is what lets one reader serve
    two policies.

    Args:
        branch_path: The branch directory holding ``.trinity/passport.json``.

    Returns:
        The declared residency string, or ``None`` when nothing is declared.
    """
    passport = Path(branch_path) / PASSPORT_RELATIVE
    try:
        data = json.loads(passport.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # DEBUG, not warning: an absent passport is an ordinary state here, not
        # a fault. It is the caller's policy that decides whether it matters —
        # a resident candidate without one is REFUSED at error level by
        # `_refuse`, and logging it twice would put a scary line under every
        # core citizen that predates passport 2.0. The event is still recorded
        # so a silent None can be traced back to a file that was never there.
        logger.debug(f"[registry_scope] No passport at {passport} — declares nothing")
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable passport {passport}: {exc}")
        return None
    residency = data.get("citizenship", {}).get("residency")
    return residency if isinstance(residency, str) else None


def resident_registry_paths(repo_root: Path | None = None) -> list[Path]:
    """Candidate resident-project registries on this machine.

    DISCOVERY ONLY — this finds files, it does not decide who is in the fleet.
    Everything here is still a candidate until :func:`declared_residency`
    speaks for it.

    The glob is deliberately shallow and registry-led.  Exactly one level under
    ``projects/``, and any dot-prefixed component refused, because ``pathlib``
    (unlike a shell) happily matches hidden directories: without that filter
    ``projects/.archive/`` walks straight back in, and with it the disposal
    zone is unreachable by construction rather than by a later name check.

    A checkout with no ``projects/`` returns empty and does not raise — CI runs
    on exactly that tree.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.

    Returns:
        Absolute registry paths, sorted, one per candidate project.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    projects = root / RESIDENT_PROJECTS_DIR
    if not projects.is_dir():
        return []

    found = []
    for path in sorted(projects.glob(RESIDENT_REGISTRY_GLOB)):
        if any(part.startswith(".") for part in path.relative_to(projects).parts):
            continue
        found.append(path)
    return found


def read_registry_branches(registry_path: Path, name_from: str = "path") -> list[dict[str, Any]]:
    """Read one registry's ACTIVE branches with absolute paths.

    Args:
        registry_path: The registry JSON file.
        name_from: ``"path"`` to name each branch by its DIRECTORY (what the
            trinity checker compares ``managed_by`` against, and what the
            per-branch config lookups key on), or ``"registry"`` to keep the
            registry's own ``name`` field, whose casing disagrees for several
            citizens (``BACKUP`` vs ``backup``).

    Returns:
        ``[{"name", "path", "registry"}]`` — empty when the file is
        unreadable, which is logged as an error rather than raised: one
        broken registry must not take out a fleet-wide lane.
    """
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable registry {registry_path}: {exc}")
        return []

    found = []
    for branch in data.get("branches", []):
        if branch.get("status") != "active":
            continue
        raw = branch.get("path", "")
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(registry_path).parent / raw
        name = path.name if name_from == "path" else branch.get("name", path.name)
        found.append({"name": name, "path": path, "registry": Path(registry_path).name})
    return found


def _refuse(item: dict[str, Any], registry_path: Path, reason: str) -> None:
    """Log a refused resident candidate by name, path and reason.

    Every rejection goes through here so none of them can be silent.  A
    candidate refused without a line in the log is indistinguishable from one
    that was never discovered, and those two need very different fixes.
    """
    logger.error(
        f"[registry_scope] REFUSED resident '{item['name']}' at {item['path']} "
        f"(listed active in {registry_path.name}): {reason}"
    )


def _accepted_residents(registry_path: Path, name_from: str) -> list[dict[str, Any]]:
    """The branches in one project registry whose passports declare them residents.

    Two keys, both required.  The registry says the branch is active — that is
    the anchor a passport cannot forge.  The passport says ``resident`` — that
    is the declaration a registry does not carry.  Anything else is refused
    and named.
    """
    accepted = []
    for item in read_registry_branches(registry_path, name_from=name_from):
        residency = declared_residency(item["path"])
        if residency == RESIDENCY_RESIDENT:
            accepted.append(item)
        elif residency is None:
            _refuse(item, registry_path, "passport declares no residency (missing, unreadable, or no field)")
        elif residency == RESIDENCY_CORE:
            _refuse(item, registry_path, f"passport declares '{RESIDENCY_CORE}' from inside {RESIDENT_PROJECTS_DIR}/")
        else:
            _refuse(item, registry_path, f"passport declares unknown residency '{residency}'")
    return accepted


def accepted_resident_paths(repo_root: Path | None = None) -> set[str]:
    """Resolved paths of every project branch whose passport declares it a resident.

    The classification, exposed once so no other lane re-implements it.
    ``detector`` reads registries in its own shape and cannot use
    :func:`fleet_branches` directly; without this it would have to repeat the
    two-key rule, and a policy with two implementations agrees only by
    coincidence — which is the exact defect this module was built to end.

    Refusals are logged by the classifier itself, so a caller filtering on this
    set stays silent and still leaves a named reason in the log.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.

    Returns:
        Absolute paths as strings, ready for membership tests.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    accepted = set()
    for registry_path in resident_registry_paths(root):
        for item in _accepted_residents(registry_path, name_from="path"):
            accepted.add(str(item["path"]))
    return accepted


def _report_drift(discovered: list[Path], root: Path) -> None:
    """Log when discovery and the demoted constant disagree.

    The constant decides nothing now.  It is kept as a tripwire so the
    transition is observable: if discovery ever stops finding a project the
    old list named, or finds one it did not, that is worth a line in the log
    rather than a silent change in fleet size.
    """
    expected = {str(root / relative) for relative in RESIDENT_REGISTRIES}
    actual = {str(path) for path in discovered}
    if expected == actual:
        return
    logger.warning(
        f"[registry_scope] Discovery differs from the demoted RESIDENT_REGISTRIES anchor — "
        f"only in discovery: {sorted(actual - expected)}; only in the anchor: {sorted(expected - actual)}"
    )


def fleet_branches(repo_root: Path | None = None, name_from: str = "path") -> list[dict[str, Any]]:
    """Every branch @memory maintains: the core citizens plus declared residents.

    Deduplicated by resolved path, core registry first, residents in discovery
    order.

    The two halves are judged by DIFFERENT rules on purpose.  Core citizens
    come from the sealed registry and are included unconditionally; a core
    passport that declares nothing, or declares something else, is logged and
    the citizen is KEPT, because an agent-writable field must never be able to
    remove its own branch from maintenance.  Resident candidates need both the
    registry entry and the declaration, because there the passport is the only
    thing distinguishing a live project from a parked one.

    Args:
        repo_root: Repo root to resolve against; defaults to this checkout's.
        name_from: See :func:`read_registry_branches`.

    Returns:
        ``[{"name", "path", "registry"}]``.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    branches = read_registry_branches(root / CORE_REGISTRY, name_from=name_from)
    core_count = len(branches)
    for item in branches:
        residency = declared_residency(item["path"])
        if residency != RESIDENCY_CORE:
            logger.warning(
                f"[registry_scope] Core citizen '{item['name']}' declares residency "
                f"{residency!r}, not '{RESIDENCY_CORE}' — kept, because the sealed registry is the anchor"
            )

    seen = {str(item["path"]) for item in branches}
    discovered = resident_registry_paths(root)
    _report_drift(discovered, root)
    for registry_path in discovered:
        for item in _accepted_residents(registry_path, name_from):
            if str(item["path"]) not in seen:
                branches.append(item)
                seen.add(str(item["path"]))

    # Logged because the SIZE of the fleet is the whole point of this module:
    # the residents were invisible to rollover, lint and health for months and
    # nothing said so. A run that quietly sees 19 branches instead of 22 is the
    # exact regression, and this line is where it shows up.
    json_handler.log_operation(
        "fleet_scope",
        {"total": len(branches), "core": core_count, "resident": len(branches) - core_count},
        module_name="registry_scope",
    )
    return branches
