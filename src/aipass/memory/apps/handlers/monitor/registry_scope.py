# =================== AIPass ====================
# Name: registry_scope.py
# Description: The one definition of "the fleet" — core, passport-declared residents, declared-root externals
# Version: 4.2.0
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Fleet Scope

Reference: docs/rollover_pipeline.md
"""

import json
from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers import repo_root
from aipass.memory.apps.handlers.json import json_handler

CORE_REGISTRY = "AIPASS_REGISTRY.json"

# Named so other branches can mirror the discovery rule without importing it.
RESIDENT_PROJECTS_DIR = "projects"
RESIDENT_REGISTRY_GLOB = "*/*_REGISTRY.json"
PASSPORT_RELATIVE = Path(".trinity") / "passport.json"

RESIDENCY_CORE = "core"
RESIDENCY_RESIDENT = "resident"

# A tier label we apply, not a passport value: external membership is presence.
RESIDENCY_EXTERNAL = "external"

DECLARED_ROOTS = "AIPASS_ROOTS.json"
EXTERNAL_REGISTRY_GLOB = "*_REGISTRY.json"

# Windows and macOS glob case-insensitively; both globs narrow to this exact case.
CORE_REGISTRY_SUFFIX = "_REGISTRY.json"


class RegistryUnreadable(RuntimeError):
    """A registry file that exists and cannot be read; raised only under ``strict=True``."""


# Tests pin this name.
_SOURCE_ROOT = repo_root.SOURCE_ROOT


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* to the registry; fall back to the source root, never cwd (runs at import)."""
    return repo_root.find_repo_root(start, marker=CORE_REGISTRY, caller="registry_scope")


REPO_ROOT = find_repo_root()


def declared_residency(branch_path: Path) -> str | None:
    """What the passport at *branch_path* declares; ``None`` for absent/unreadable/misshapen, never raises."""
    passport = Path(branch_path) / PASSPORT_RELATIVE
    try:
        data = json.loads(passport.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # DEBUG: `_refuse` already logs a resident candidate's absence at error.
        logger.debug(f"[registry_scope] No passport at {passport} — declares nothing")
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable passport {passport}: {exc}")
        return None
    if not isinstance(data, dict):
        logger.error(f"[registry_scope] Passport root is {type(data).__name__}, not an object: {passport}")
        return None
    citizenship = data.get("citizenship")
    if not isinstance(citizenship, dict):
        if citizenship is not None:
            logger.error(f"[registry_scope] Passport citizenship is {type(citizenship).__name__} in {passport}")
        return None
    residency = citizenship.get("residency")
    return residency if isinstance(residency, str) else None


def resident_registry_paths(repo_root: Path | None = None) -> list[Path]:
    """Candidate resident-project registries on this machine (discovery, not membership).

    Registries, never passports: a passport walk counts ``.backup/`` copies.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    projects = root / RESIDENT_PROJECTS_DIR
    if not projects.is_dir():
        return []

    found = []
    for path in _exactly_named(sorted(projects.glob(RESIDENT_REGISTRY_GLOB)), CORE_REGISTRY_SUFFIX):
        # pathlib globs hidden dirs; this keeps projects/.archive/ out.
        if any(part.startswith(".") for part in path.relative_to(projects).parts):
            continue
        found.append(path)
    return found


def _exactly_named(candidates: list[Path], suffix: str) -> list[Path]:
    """Keep only names ending with *suffix* in exact case; the walks treat the match count as meaningful."""
    return repo_root.exactly_named(candidates, suffix)


def _registry_rows(registry_path: Path) -> list[Any]:
    """The raw ``branches`` list of one registry file; raises RegistryUnreadable on any bad shape."""
    try:
        data = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegistryUnreadable(f"Unreadable registry {registry_path}: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryUnreadable(f"Unreadable registry {registry_path}: root is {type(data).__name__}, not an object")
    branches = data.get("branches", [])
    if not isinstance(branches, list):
        raise RegistryUnreadable(
            f"Unreadable registry {registry_path}: 'branches' is {type(branches).__name__}, not a list"
        )
    return branches


def read_registry_branches(registry_path: Path, name_from: str = "path", strict: bool = False) -> list[dict[str, Any]]:
    """Read one registry's ACTIVE branches with absolute paths.

    ``name_from="path"`` names by directory (what ``managed_by`` keys on); ``"registry"`` keeps its casing.
    """
    try:
        branches = _registry_rows(registry_path)
    except RegistryUnreadable as exc:
        if strict:
            raise
        logger.error(f"[registry_scope] {exc}")
        return []

    found = []
    for branch in branches:
        # One bad row costs one row, never the whole registry.
        if not isinstance(branch, dict):
            logger.error(f"[registry_scope] Registry row is {type(branch).__name__}, not an object: {registry_path}")
            continue
        if branch.get("status") != "active":
            continue
        raw = branch.get("path", "")
        if not isinstance(raw, str):
            logger.error(
                f"[registry_scope] Registry row '{branch.get('name')}' has a non-string path in {registry_path}"
            )
            continue
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = Path(registry_path).parent / raw
        name = path.name if name_from == "path" else branch.get("name", path.name)
        # A bad address has no honest fallback, unlike a name: it becomes None.
        if not isinstance(name, str):
            logger.error(f"[registry_scope] Registry row at {raw} has a non-string name in {registry_path}")
            name = path.name
        email = branch.get("email")
        if email is not None and not isinstance(email, str):
            logger.error(f"[registry_scope] Registry row '{name}' has a non-string email in {registry_path}")
            email = None
        # Never derive an address from ``name``: a plausible wrong address is worse than None.
        found.append(
            {
                "name": name,
                "path": path,
                "registry": Path(registry_path).name,
                "email": email or None,
            }
        )
    return found


def overlaps_home(candidate: Path, home: Path) -> bool:
    """Does resolved *candidate* overlap AIPass home? Public: the roots write lane refuses against it too."""
    return candidate == home or home in candidate.parents or candidate in home.parents


def declared_roots(repo_root: Path | None = None) -> list[Path]:
    """Repo roots this installation has DECLARED as participating, resolved, in declaration order."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    anchor = root / DECLARED_ROOTS
    try:
        data = json.loads(anchor.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.debug(f"[registry_scope] No {DECLARED_ROOTS} at {root} — no external roots declared")
        return []
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.error(f"[registry_scope] Unreadable {DECLARED_ROOTS} at {anchor}: {exc}")
        return []

    if not isinstance(data, dict):
        logger.error(f"[registry_scope] {DECLARED_ROOTS} root is {type(data).__name__}, not an object: {anchor}")
        return []
    rows = data.get("roots", [])
    if not isinstance(rows, list):
        logger.error(f"[registry_scope] {DECLARED_ROOTS} 'roots' is {type(rows).__name__}, not a list: {anchor}")
        return []

    home = root.resolve()
    found: list[Path] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            logger.error(f"[registry_scope] {DECLARED_ROOTS} row is {type(row).__name__}, not an object: {anchor}")
            continue
        if row.get("status") != "active":
            logger.info(f"[registry_scope] Declared root {row.get('path')!r} is not active — skipped")
            continue
        raw = row.get("path")
        if not isinstance(raw, str) or not raw:
            logger.error(f"[registry_scope] Declared root has no usable path ({raw!r}) in {anchor}")
            continue

        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
        except OSError as exc:
            logger.error(f"[registry_scope] Declared root {raw!r} cannot be resolved: {exc}")
            continue
        if not candidate.is_dir():
            logger.error(f"[registry_scope] Declared root {raw!r} is not a directory on this machine ({candidate})")
            continue
        if overlaps_home(candidate, home):
            logger.error(
                f"[registry_scope] REFUSED declared root {raw!r} ({candidate}): it overlaps AIPass home "
                f"{home} — core and resident citizens would be counted twice"
            )
            continue

        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)

    # Not sorted(): declaration order is the tie-breaker.
    return found


def external_branches(repo_root: Path | None = None, name_from: str = "path") -> list[dict[str, Any]]:
    """Citizens in declared roots outside this repo; membership is presence of a passport."""
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in declared_roots(repo_root):
        registries = _exactly_named(sorted(root.glob(EXTERNAL_REGISTRY_GLOB)), CORE_REGISTRY_SUFFIX)
        if not registries:
            logger.error(
                f"[registry_scope] Declared root {root} carries no {EXTERNAL_REGISTRY_GLOB} at its top level — "
                "no citizens read from it, and a passport walk is never the fallback"
            )
            continue
        if len(registries) > 1:
            # Neither pick sorted()[0] nor merge: both invent a fleet nobody declared.
            logger.error(
                f"[registry_scope] REFUSED declared root {root}: it carries {len(registries)} registries "
                f"({', '.join(path.name for path in registries)}) — which one is the fleet is not ours to guess"
            )
            continue
        for registry_path in registries:
            for item in read_registry_branches(registry_path, name_from=name_from):
                if not (item["path"] / PASSPORT_RELATIVE).is_file():
                    _refuse(
                        item,
                        registry_path,
                        "no passport on disk — external membership is presence",
                        tier=RESIDENCY_EXTERNAL,
                    )
                    continue
                key = str(item["path"])
                if key in seen:
                    continue
                seen.add(key)
                item["residency"] = RESIDENCY_EXTERNAL
                found.append(item)
    return found


def _refuse(item: dict[str, Any], registry_path: Path, reason: str, tier: str = RESIDENCY_RESIDENT) -> None:
    """Log a refused candidate by tier, name, path and reason; no refusal is silent."""
    logger.error(
        f"[registry_scope] REFUSED {tier} '{item['name']}' at {item['path']} "
        f"(listed active in {registry_path.name}): {reason}"
    )


def _accepted_residents(registry_path: Path, name_from: str) -> list[dict[str, Any]]:
    """Branches active in one project registry AND whose passports declare ``resident``."""
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
    """Resolved resident paths, exposed so ``detector`` does not re-implement the two-key rule."""
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    accepted = set()
    for registry_path in resident_registry_paths(root):
        for item in _accepted_residents(registry_path, name_from="path"):
            accepted.add(str(item["path"]))
    return accepted


def fleet_branches(
    repo_root: Path | None = None, name_from: str = "path", strict: bool = False
) -> list[dict[str, Any]]:
    """Every branch @memory maintains: core citizens, residents, and externals.

    ``strict`` is for by-name writers: with core rows gone, a same-named resident would answer.
    """
    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    core = root / CORE_REGISTRY
    branches = read_registry_branches(core, name_from=name_from, strict=strict and core.exists())
    core_count = len(branches)
    for item in branches:
        residency = declared_residency(item["path"])
        # Kept anyway: an agent-writable field must never remove its own branch.
        if residency != RESIDENCY_CORE:
            logger.warning(
                f"[registry_scope] Core citizen '{item['name']}' declares residency "
                f"{residency!r}, not '{RESIDENCY_CORE}' — kept, because the sealed registry is the anchor"
            )

    # The tier is applied, not read from the passport: externals declare nothing.
    for item in branches:
        item["residency"] = RESIDENCY_CORE

    seen = {str(item["path"]) for item in branches}
    for registry_path in resident_registry_paths(root):
        for item in _accepted_residents(registry_path, name_from):
            if str(item["path"]) not in seen:
                item["residency"] = RESIDENCY_RESIDENT
                branches.append(item)
                seen.add(str(item["path"]))
    resident_count = len(branches) - core_count

    for item in external_branches(root, name_from=name_from):
        if str(item["path"]) not in seen:
            branches.append(item)
            seen.add(str(item["path"]))

    # A shrunken fleet is the regression this module exists to prevent; log its size.
    json_handler.log_operation(
        "fleet_scope",
        {
            "total": len(branches),
            "core": core_count,
            "resident": resident_count,
            "external": len(branches) - core_count - resident_count,
        },
        module_name="registry_scope",
    )
    return branches
