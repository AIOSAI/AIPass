# =================== AIPass ====================
# Name: registry_handler.py
# Description: Handler for registry file operations
# Version: 1.1.0
# Created: 2026-03-09
# Modified: 2026-08-30
# =============================================

"""
Handler for registry file operations.

Handles loading, parsing, and normalizing *_REGISTRY.json files.
All file I/O and data transformation for the registry lives here.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger
from aipass.memory.apps.modules import fleet
from .exceptions import (
    RegistryCorruptError,
    RegistryMismatchError,
    RegistryNotFoundError,
    RegistryPermissionError,
)
from aipass.drone.apps.handlers.json import json_handler
from .router_handler import caller_cwd


# ---------------------------------------------------------------------------
# Path containment validation
# ---------------------------------------------------------------------------


def _validate_branch_path(branch_path: Path, project_root: Path, branch_name: str) -> bool:
    """Validate that a resolved branch path is contained within the project root.

    Returns True if the path is safe.  Returns False and logs a warning if
    the path escapes the project boundary (path-traversal / ghost-branch).
    """
    try:
        resolved = branch_path.resolve()
        root = project_root.resolve()
        if not resolved.is_relative_to(root):
            logger.warning(
                "SECURITY: branch '%s' path escapes project root: %s (root: %s)",
                branch_name,
                resolved,
                root,
            )
            return False
    except (OSError, ValueError) as exc:
        logger.warning(
            "SECURITY: branch '%s' path validation failed: %s",
            branch_name,
            exc,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# Registry path resolution
# ---------------------------------------------------------------------------

_registry_path: Optional[Path] = None


def _first_registry_in(directory: Path) -> Optional[Path]:
    """Return the first *_REGISTRY.json in *directory*, or None.

    When multiple matches exist, the alphabetically-first name wins
    so the result is deterministic across platforms.
    """
    matches = sorted(directory.glob("*_REGISTRY.json"))
    return matches[0] if matches else None


def _registry_matches_credential(registry_path: Path) -> bool:
    """Check whether a candidate registry matches the nearest passport.

    Returns True when the registry is acceptable (IDs match, either side is
    missing an ID, or the caller has no directory to walk from).  Returns False
    only when both IDs exist and disagree — the caller should skip this registry
    and keep walking.

    DECLARED ROOTS DO NOT COME THROUGH HERE, AND THAT IS DELIBERATE.
    DECLARATION IS THE CREDENTIAL (@devpulse's ruling, FPLAN-0460 phase 3).
    This gate asks an INTRA-installation question — "are you a citizen of the
    registry you are standing in" — and a cross-repo answer is not available to
    it, because the ids differ BY CONSTRUCTION: AIPASS 7087bb93, VERA-STUDIO
    8fb38c96, WREN 9d11c395. Routing every external root through this check
    would refuse all of them, always, for being what they are.

    The authority a walk could never attach is Patrick blessing
    AIPASS_ROOTS.json. That file is the credential, and @memory's reader is the
    only thing that reads it.

    NOTE FOR WHOEVER FINDS THE UNCHECKED PATH LATER: the AIPASS_HOME fallback in
    find_registry() has never been credential-checked either, and neither is the
    external tier below. That is not an oversight to fix. "Fixing" it silently
    kills every external citizen — the fence test (@wren) simply stops
    resolving, with no error, because being refused is indistinguishable from
    never having been declared.
    """
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        registry_id = data.get("metadata", {}).get("id") if isinstance(data, dict) else None
        if not registry_id:
            return True

        cwd = caller_cwd()
        if cwd is None:
            # No location is not a failed check. The walk below infers from
            # where the caller STANDS, and a process whose directory was
            # deleted stands nowhere — the same answer as a walk that finds no
            # passport, reached honestly instead of through the except below
            # logging "pre-check failed" for a check that did not fail.
            logger.info(
                "Credential pre-check for %s has no current directory to walk from — "
                "no passport is reachable, so the registry is accepted",
                registry_path,
            )
            return True

        for parent in [cwd] + list(cwd.parents):
            candidate = parent / ".trinity" / "passport.json"
            if candidate.is_file():
                with open(candidate, "r", encoding="utf-8") as f:
                    passport = json.load(f)
                passport_id = passport.get("citizenship", {}).get("registry_id")
                if not passport_id:
                    return True
                return passport_id == registry_id
        return True
    except Exception as exc:
        logger.warning("Credential pre-check failed for %s: %s", registry_path, exc)
        return True


def find_registry() -> Path:
    """Find a *_REGISTRY.json by walking up from this file's location.

    Search order:
    1. Explicitly set path via set_registry_path()
    2. AIPASS_REGISTRY environment variable
    3. Walk up from cwd (skipping registries that fail credential check)
    4. AIPASS_HOME env var — for external projects where CWD walk finds nothing
    5. Walk up from drone package location
    6. Default: package-relative path

    When a candidate registry's metadata.id conflicts with the nearest
    passport's registry_id, it is skipped and the walk continues upward.
    """
    # Walk up from cwd FIRST — this is where the user is working. A caller
    # whose directory was deleted has no "where", so step 3 is SKIPPED rather
    # than attempted: the remaining sources (AIPASS_HOME, the package walk)
    # never depended on a location and still answer.
    cwd = caller_cwd()
    if cwd is not None:
        for parent in [cwd] + list(cwd.parents):
            hit = _first_registry_in(parent)
            if hit is not None:
                if _registry_matches_credential(hit):
                    return hit
                continue

    # AIPASS_HOME fallback — for external projects where CWD walk finds nothing
    aipass_home = os.environ.get("AIPASS_HOME")
    if aipass_home:
        hit = _first_registry_in(Path(aipass_home))
        if hit is not None:
            return hit

    # Walk up from this file (fallback for pip editable installs)
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        hit = _first_registry_in(parent)
        if hit is not None:
            return hit

    # Fallback — walk up from this file to the project root (marker-based)
    _markers = (".git", "pyproject.toml", "setup.py", "setup.cfg")
    fallback_dir = Path(__file__).resolve().parent
    for parent in [fallback_dir, *fallback_dir.parents]:
        if any((parent / m).exists() for m in _markers):
            fallback_dir = parent
            break
    hit = _first_registry_in(fallback_dir)
    if hit is not None:
        return hit
    return fallback_dir / "AIPASS_REGISTRY.json"


def get_registry_path() -> Path:
    """Get the current registry path.

    Priority:
    1. Explicitly set path via set_registry_path()
    2. AIPASS_REGISTRY environment variable
    3. Walk-up finder from package location
    """
    global _registry_path

    if _registry_path is not None:
        return _registry_path

    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:
        return Path(env_path)

    return find_registry()


def _verify_registry_credential(registry_path: Path, registry_data: Dict[str, Any]) -> None:
    """Verify that the registry matches the caller's passport credential.

    Compares registry metadata.id against the nearest passport's
    citizenship.registry_id.  Only raises when BOTH sides have an ID
    and they don't match — silent pass otherwise.
    """
    try:
        registry_id = registry_data.get("metadata", {}).get("id")
        if not registry_id:
            return

        # Walk up from CWD looking for .trinity/passport.json. No location
        # means no passport to compare against — the same silent pass as a walk
        # that finds none, said at INFO instead of arriving as a warning about
        # a verification that never failed.
        cwd = caller_cwd()
        if cwd is None:
            logger.info(
                "Registry credential verification for %s has no current directory to walk from — "
                "no passport is reachable, so there is nothing to compare",
                registry_path,
            )
            return

        passport_path = None
        for parent in [cwd] + list(cwd.parents):
            candidate = parent / ".trinity" / "passport.json"
            if candidate.is_file():
                passport_path = candidate
                break

        if passport_path is None:
            return

        with open(passport_path, "r", encoding="utf-8") as f:
            passport = json.load(f)

        passport_id = passport.get("citizenship", {}).get("registry_id")
        if not passport_id:
            return

        if passport_id != registry_id:
            raise RegistryMismatchError(
                f"Registry mismatch: citizen belongs to registry "
                f"'{passport_id}' but found registry '{registry_id}' "
                f"at {registry_path}"
            )
    except RegistryMismatchError:
        raise
    except Exception as exc:
        logger.warning("Registry credential verification failed: %s", exc)


def set_registry_path(path: str | Path) -> None:
    """Set a custom registry path."""
    global _registry_path
    _registry_path = Path(path)


def reset_registry_path() -> None:
    """Reset registry path to default (useful for testing)."""
    global _registry_path
    _registry_path = None


# ---------------------------------------------------------------------------
# Registry loading and querying
# ---------------------------------------------------------------------------


def _load_registry_data(registry_path: Path) -> Dict[str, Any]:
    """Read, parse, and normalize a registry file.

    Performs file I/O and branch normalization (list → dict).  Does NOT
    run credential verification or log the operation — callers that need
    those steps (i.e. load_registry) are responsible.

    Raises:
        RegistryNotFoundError: If registry file doesn't exist
        RegistryCorruptError: If registry file is invalid JSON or malformed
        RegistryPermissionError: If registry file cannot be read
    """
    if not registry_path.exists():
        raise RegistryNotFoundError(
            f"Registry not found at {registry_path}. Create a *_REGISTRY.json file in your project root."
        )

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except PermissionError as e:
        raise RegistryPermissionError(f"Permission denied reading registry: {e}")
    except json.JSONDecodeError as e:
        raise RegistryCorruptError(f"Registry file is corrupted: {e}")
    except Exception as e:
        raise RegistryCorruptError(f"Failed to read registry: {e}")

    if not isinstance(data, dict):
        raise RegistryCorruptError("Registry must be a JSON object")

    if "branches" not in data:
        raise RegistryCorruptError("Registry missing 'branches' field")

    # Normalize: AIPASS_REGISTRY uses list format, convert to dict keyed by name
    branches_raw = data["branches"]
    if isinstance(branches_raw, list):
        branches_dict: Dict[str, Any] = {}
        registry_dir = registry_path.parent
        for branch in branches_raw:
            name = branch.get("name", "").lower()
            if not name:
                continue
            # Resolve relative paths against registry location
            raw_path = branch.get("path", "")
            branch_path = Path(raw_path)
            if not branch_path.is_absolute():
                branch_path = (registry_dir / branch_path).resolve()
            if not _validate_branch_path(branch_path, registry_dir, name):
                continue
            entry = dict(branch)
            entry["name"] = name
            entry["path"] = str(branch_path)
            branches_dict[name] = entry
        data["branches"] = branches_dict
    elif not isinstance(branches_raw, dict):
        raise RegistryCorruptError("Registry 'branches' must be a list or dict")

    return data


def _get_aipass_home_registry_path() -> Optional[Path]:
    """Return the AIPass home registry path from AIPASS_HOME env var, or None."""
    aipass_home = os.environ.get("AIPASS_HOME")
    if not aipass_home:
        return None
    return _first_registry_in(Path(aipass_home))


def load_registry() -> Dict[str, Any]:
    """Load the branch registry from disk.

    Returns:
        Registry dictionary with branches (normalized to dict format)

    Raises:
        RegistryNotFoundError: If registry file doesn't exist
        RegistryCorruptError: If registry file is invalid JSON
        RegistryPermissionError: If registry file cannot be read
    """
    registry_path = get_registry_path()
    data = _load_registry_data(registry_path)

    _verify_registry_credential(registry_path, data)

    branch_count = len(data.get("branches", {}))
    json_handler.log_operation("load_registry", {"path": str(registry_path), "branch_count": branch_count})

    return data


def _external_branches(repo_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Citizens in declared roots, in DECLARATION ORDER, as registry entries.

    Consumes @memory's public gateway and never reads AIPASS_ROOTS.json — the
    file has exactly one reader and it is theirs. A second reader here would be
    the two-implementations failure the gateway exists to prevent, and it would
    drift the first time their schema moved.

    Keyed the way local branches are: the registry's own ``name`` field,
    lowercased. ``name_from="registry"`` is not a preference — local resolution
    keys on that field (see _load_registry_data), and giving the external tier a
    different rule would mean ``@wren`` resolving by one law and ``@memory`` by
    another.

    Returns [] and says so LOUDLY when the gateway fails. An empty declared-roots
    file is a legal state and silent; another branch's module raising is not.
    """
    # Scoped to the project being resolved AGAINST, not to this checkout.
    # get_all_branches(registry=X) must read X's declared roots, so an external
    # project resolves through its own AIPASS_ROOTS.json and a caller that
    # repoints the registry is not silently answered with ours.
    #
    # This is also the isolation seam the other two sources already have: the
    # AIPASS_HOME source is switched off by unsetting its env var, and without
    # an equivalent here the real machine's declared roots leaked into every
    # enumeration test the moment Patrick blessed the file. A third source with
    # no way to scope it is a third source that cannot be tested around.
    if repo_root is None:
        try:
            repo_root = get_registry_path().parent
        except Exception as exc:
            logger.warning("External tier: cannot locate a project root to scope declared roots: %s", exc)
            return []

    try:
        records = fleet.external_branches(repo_root, name_from="registry")
    except Exception as exc:
        logger.error(
            "External tier unavailable — @memory's fleet gateway raised: %s. "
            "Local and AIPASS_HOME resolution continue; declared-root citizens do not resolve.",
            exc,
        )
        return []

    entries: List[Dict[str, Any]] = []
    for record in records:
        name = str(record.get("name", "")).lower()
        path = record.get("path")
        registry_name = record.get("registry")
        if not name or path is None or not registry_name:
            logger.warning("Skipping malformed external record from the fleet gateway: %r", record)
            continue
        entries.append(
            {
                "name": name,
                "path": str(path),
                "email": record.get("email"),
                "status": "active",
                "residency": record.get("residency"),
                "registry": registry_name,
            }
        )
    return entries


def _external_registry_path(entry: Dict[str, Any]) -> Optional[Path]:
    """The sealed registry an external entry was read from.

    Derived by containment, never by walking up: the gateway hands back the
    branch path and its registry FILENAME, and the declared root is the only
    ancestor holding that file.
    """
    branch_path = Path(entry["path"])
    for root in [branch_path, *branch_path.parents]:
        candidate = root / entry["registry"]
        if candidate.is_file():
            return candidate
    logger.warning(
        "External citizen '%s' names registry %s but it was not found above %s",
        entry["name"],
        entry["registry"],
        entry["path"],
    )
    return None


def get_all_branches(
    branch_type: Optional[str] = None,
    status: str = "active",
) -> List[Dict[str, Any]]:
    """Get all branches from the registry, optionally filtered.

    Merges branches from both the primary (local/project) registry and the
    AIPass home registry (from AIPASS_HOME env var).  Local branches take
    precedence when names collide.
    """
    merged: Dict[str, Any] = {}

    # --- Primary registry ---
    try:
        primary = load_registry()
        for name, branch in primary.get("branches", {}).items():
            merged[name] = branch
    except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
        logger.warning("get_all_branches: primary registry unavailable: %s", exc)

    # --- AIPass home registry (if different from primary) ---
    home_path = _get_aipass_home_registry_path()
    primary_path = get_registry_path()
    if home_path is not None and home_path != primary_path:
        try:
            home_data = _load_registry_data(home_path)
            for name, branch in home_data.get("branches", {}).items():
                if name not in merged:
                    merged[name] = branch
        except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
            logger.warning("get_all_branches: AIPass home registry unavailable: %s", exc)

    # --- Declared roots (external tier) ---
    # Last on purpose: AIPass local ALWAYS wins, and among externals the
    # declaration order in roots[] breaks ties. Both are @devpulse's ruling.
    # This is the one place both sides of a collision are visible at once, so it
    # is where the collision is named — a shadowed citizen that vanishes without
    # a line is indistinguishable from one that was never declared.
    for entry in _external_branches():
        name = entry["name"]
        if name in merged:
            logger.warning(
                "Name collision: '%s' is declared by external root %s (%s) and is SHADOWED by %s. "
                "The external citizen is unreachable by name until one side renames.",
                name,
                entry["registry"],
                entry["path"],
                merged[name].get("path"),
            )
            continue
        merged[name] = entry

    filtered = []
    for branch in merged.values():
        if status and branch.get("status") != status:
            continue
        if branch_type and branch.get("type") != branch_type:
            continue
        filtered.append(branch)

    return filtered


def get_branch_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get a single branch by name (case-insensitive).

    Checks the primary (local/project) registry first.  If not found, falls
    back to the AIPass home registry (AIPASS_HOME env var) when it points to
    a different location.
    """
    lower_name = name.lower()

    # --- Primary registry ---
    try:
        registry = load_registry()
        branch = registry.get("branches", {}).get(lower_name)
        if branch is not None:
            return branch
    except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
        logger.warning("get_branch_by_name: primary registry unavailable for '%s': %s", name, exc)

    # --- AIPass home registry fallback ---
    home_path = _get_aipass_home_registry_path()
    primary_path = get_registry_path()
    if home_path is not None and home_path != primary_path:
        try:
            home_data = _load_registry_data(home_path)
            branch = home_data.get("branches", {}).get(lower_name)
            if branch is not None:
                return branch
            # A MISS here is not an answer. This used to return the lookup
            # itself, so on any machine where AIPass home is not the project
            # registry, an unknown name ended the search here and the declared
            # roots below were unreachable. get_branch_with_registry has always
            # guarded the identical lookup this way.
        except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
            logger.warning("get_branch_by_name: AIPass home registry unavailable for '%s': %s", name, exc)

    # --- Declared roots (external tier) ---
    # Consulted only after both local sources miss, so a local citizen never
    # pays a cross-repo read to resolve. First match wins, and the gateway
    # returns declaration order, so the tiebreak is the file's own ordering.
    for entry in _external_branches():
        if entry["name"] == lower_name:
            logger.info("Resolved '%s' from declared root %s", lower_name, entry["registry"])
            return entry

    return None


def get_branch_with_registry(name: str) -> Optional[tuple]:
    """Get a branch and the registry path it was found in.

    Same two-step lookup as get_branch_by_name (primary then AIPASS_HOME),
    but returns (branch_dict, registry_path) so callers can determine
    which project root the branch belongs to.
    """
    lower_name = name.lower()

    try:
        primary_path = get_registry_path()
        registry = load_registry()
        branch = registry.get("branches", {}).get(lower_name)
        if branch is not None:
            return branch, primary_path
    except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
        logger.warning("get_branch_with_registry: primary registry unavailable for '%s': %s", name, exc)
        primary_path = None

    home_path = _get_aipass_home_registry_path()
    if home_path is not None and home_path != primary_path:
        try:
            home_data = _load_registry_data(home_path)
            branch = home_data.get("branches", {}).get(lower_name)
            if branch is not None:
                return branch, home_path
        except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
            logger.warning("get_branch_with_registry: AIPass home registry unavailable for '%s': %s", name, exc)

    # --- Declared roots (external tier) ---
    for entry in _external_branches():
        if entry["name"] == lower_name:
            external_registry = _external_registry_path(entry)
            if external_registry is None:
                continue
            logger.info("Resolved '%s' from declared root %s", lower_name, external_registry)
            return entry, external_registry

    return None
