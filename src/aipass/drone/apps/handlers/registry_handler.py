# =================== AIPass ====================
# Name: registry_handler.py
# Description: Handler for registry file operations
# Version: 1.4.0
# Created: 2026-03-09
# Modified: 2026-10-17
# =============================================

"""
Handler for registry file operations.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from aipass.prax import logger
from .exceptions import (
    RegistryCorruptError,
    RegistryMismatchError,
    RegistryNotFoundError,
    RegistryPermissionError,
)
from aipass.drone.apps.handlers.json import json_handler
from .router_handler import caller_cwd, registries_in


def _validate_branch_path(branch_path: Path, project_root: Path, branch_name: str) -> bool:
    """Validate that a resolved branch path is contained within the project root."""
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


_registry_path: Optional[Path] = None

#: The first unreadable passport, as the line main() prints on stderr after routing.
_PASSPORT_FAULT: Optional[str] = None


def passport_fault() -> Optional[str]:
    """The line naming a passport the credential checks could not read, or None.

    Both checks accept the registry when the passport cannot be read: refusing
    would send find_registry() to another project's registry with no word said.
    """
    return _PASSPORT_FAULT


def _record_passport_fault(passport_path: Path, registry_path: Path, exc: Exception) -> None:
    """Record the first unreadable passport; a later read of the same fault says nothing new."""
    global _PASSPORT_FAULT
    if _PASSPORT_FAULT is not None:
        return
    _PASSPORT_FAULT = (
        f"drone: passport {passport_path} could not be read ({type(exc).__name__}: {exc}); "
        f"registry {registry_path} was used without its credential check"
    )
    logger.warning("%s", _PASSPORT_FAULT)


# The registry that marks a directory as an AIPass home, not a project's own.
HOME_REGISTRY = "AIPASS_REGISTRY.json"


class AipassHome(NamedTuple):
    """Where the AIPass home is, which source named it, and what was tried when none did."""

    path: Optional[Path]
    source: str
    tried: tuple


def _interpreter_home() -> Path:
    """The directory holding this interpreter's venv: ``<home>`` for ``<home>/.venv/bin/python3``."""
    return Path(sys.prefix).parent


def _enrolment_file() -> Optional[Path]:
    """``~/.aipass/trusted_projects.json``, or None when there is no user home directory to look in."""
    try:
        return Path.home() / ".aipass" / "trusted_projects.json"
    except RuntimeError as exc:
        logger.warning("AIPass home: no user home directory to find the enrolment file in: %s", exc)
        return None


def _enrolled_homes(enrolment: Path) -> List[tuple]:
    """``(enrolled, path)`` for each enrolled project that holds an AIPASS_REGISTRY.json.

    Raises OSError or ValueError on an unreadable file: a fault to name, never "nothing enrolled".
    """
    data = json.loads(enrolment.read_text(encoding="utf-8"))
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        raise ValueError("'projects' is not an object")
    homes = []
    for raw, entry in projects.items():
        path = Path(raw)
        if (path / HOME_REGISTRY).is_file():
            enrolled = entry.get("enrolled", "") if isinstance(entry, dict) else ""
            homes.append((str(enrolled), path))
    return homes


def resolve_aipass_home() -> AipassHome:
    """The AIPass home: the one answer every AIPASS_HOME reader in drone asks.

    First answer wins: ``AIPASS_HOME`` as given; the interpreter's ``<home>/.venv``
    parent when it holds an AIPASS_REGISTRY.json; the newest enrolled home in
    ``~/.aipass/trusted_projects.json``. ``path`` is None only when all three
    failed, and ``tried`` then names each for the tip.
    """
    explicit = os.environ.get("AIPASS_HOME")
    if explicit:
        return AipassHome(Path(explicit), "AIPASS_HOME", ())

    tried = ["AIPASS_HOME is unset"]
    interpreter_home = _interpreter_home()
    if (interpreter_home / HOME_REGISTRY).is_file():
        return AipassHome(interpreter_home, "interpreter", ())
    tried.append(f"{interpreter_home} (the interpreter's install) holds no {HOME_REGISTRY}")

    homes, why_none = _enrolled_or_reason(_enrolment_file())
    if not homes:
        tried.append(why_none)
        return AipassHome(None, "", tuple(tried))
    enrolled, home = max(homes, key=lambda pair: pair[0])
    if len(homes) > 1:
        logger.info("AIPass home: %d enrolled homes; chose %s, the newest enrolled (%s)", len(homes), home, enrolled)
    return AipassHome(home, "enrolled", ())


def _enrolled_or_reason(enrolment: Optional[Path]) -> tuple:
    """``(homes, "")`` from the enrolment file, or ``([], why there are none)``."""
    if enrolment is None:
        return [], "there is no user home directory holding .aipass/trusted_projects.json"
    if not enrolment.is_file():
        return [], f"{enrolment} does not exist"
    try:
        homes = _enrolled_homes(enrolment)
    except (OSError, ValueError) as exc:
        logger.warning("AIPass home: the enrolment file %s could not be read: %s", enrolment, exc)
        return [], f"{enrolment} could not be read ({exc})"
    if not homes:
        return [], f"{enrolment} enrolls no project holding {HOME_REGISTRY}"
    return homes, ""


def missing_home_tip() -> str:
    """The tip printed under "Branch not found", or "" when an AIPass home resolved."""
    home = resolve_aipass_home()
    if home.path is not None:
        return ""
    return (
        "  Tip: no AIPass home found. Tried: "
        + "; ".join(home.tried)
        + ".\n  Set AIPASS_HOME=/path/to/AIPass to reach the core branches."
    )


# Homes whose interpreter choice is already logged: once per home, not per command.
_ANNOUNCED_HOMES: set = set()


VENV_LAYOUTS = {"windows": ("Scripts", "python.exe"), "posix": ("bin", "python")}


def _venv_layout() -> tuple:
    """This platform's venv layout, one of VENV_LAYOUTS."""
    return VENV_LAYOUTS["windows"] if os.name == "nt" else VENV_LAYOUTS["posix"]


def _venv_python(home: Path) -> Path:
    """Where setup.sh puts the home's own interpreter: ``<home>/.venv/bin/python`` or ``Scripts/python.exe``."""
    directory, name = _venv_layout()
    return home / ".venv" / directory / name


def branch_interpreter(branch_path: str | Path) -> str:
    """Which python runs a branch's app: the interpreter of the AIPass home the branch lives in.

    A home app run on the uv tool venv's python imports the tool's handlers,
    and the handlers fence refuses a caller outside its tree.
    The venv path is returned unresolved: a venv's python is a symlink to the
    base interpreter, and following it would lose the venv.
    """
    home = resolve_aipass_home().path
    if home is None:
        return sys.executable
    home = home.resolve()
    if not Path(branch_path).resolve().is_relative_to(home) or home == _interpreter_home().resolve():
        return sys.executable
    venv_python = _venv_python(home)
    announce = home not in _ANNOUNCED_HOMES
    _ANNOUNCED_HOMES.add(home)
    if venv_python.is_file():
        if announce:
            logger.info(
                "Branch apps in the AIPass home %s run on its own interpreter %s; this drone's %s belongs to "
                "another install",
                home,
                venv_python,
                sys.executable,
            )
        return str(venv_python)
    if announce:
        logger.warning(
            "The AIPass home %s has no %s (setup.sh makes it; this home is half-installed). "
            "Its branch apps run on this drone's own %s, whose handlers may refuse them.",
            home,
            venv_python,
            sys.executable,
        )
    return sys.executable


def _first_registry_in(directory: Path) -> Optional[Path]:
    """Return the alphabetically-first *_REGISTRY.json in *directory*, or None."""
    matches = registries_in(directory)
    return matches[0] if matches else None


def _registry_matches_credential(registry_path: Path) -> bool:
    """Check whether a candidate registry matches the nearest passport.

    False only when both IDs exist and disagree: the caller skips it and keeps walking.
    Declared roots and the AIPASS_HOME fallback never pass through here, on purpose:
    registry ids differ across installations by construction, so checking them
    would silently refuse every external citizen. Declaration is the credential.
    """
    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        registry_id = data.get("metadata", {}).get("id") if isinstance(data, dict) else None
    except Exception as exc:
        # Accepted: load_registry() reads the same file and raises with its name;
        # skipping would resolve another registry further up without a word.
        logger.warning("Credential pre-check could not read registry %s: %s", registry_path, exc)
        return True
    if not registry_id:
        return True

    cwd = caller_cwd()
    if cwd is None:
        logger.info(
            "Credential pre-check for %s has no current directory to walk from — "
            "no passport is reachable, so the registry is accepted",
            registry_path,
        )
        return True

    candidate = cwd / ".trinity" / "passport.json"
    try:
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
        # Accepted loudly: refusing would send the walk to another project's registry in silence.
        _record_passport_fault(candidate, registry_path, exc)
        return True


def find_registry() -> Path:
    """Find a *_REGISTRY.json by walking up from this file's location.

    Order: walk up from cwd (skipping credential mismatches), the AIPass home,
    walk up from this package, then the package's project root.
    """
    cwd = caller_cwd()
    if cwd is not None:
        for parent in [cwd] + list(cwd.parents):
            hit = _first_registry_in(parent)
            if hit is not None:
                if _registry_matches_credential(hit):
                    return hit
                continue

    hit = _get_aipass_home_registry_path()
    if hit is not None:
        return hit

    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        hit = _first_registry_in(parent)
        if hit is not None:
            return hit

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
    """Get the current registry path: set_registry_path(), else AIPASS_REGISTRY, else find_registry()."""
    global _registry_path

    if _registry_path is not None:
        return _registry_path

    env_path = os.environ.get("AIPASS_REGISTRY")
    if env_path:
        return Path(env_path)

    return find_registry()


def _verify_registry_credential(registry_path: Path, registry_data: Dict[str, Any]) -> None:
    """Verify that the registry matches the caller's passport credential.

    Raises only when BOTH sides have an ID and they differ; silent pass otherwise.
    """
    try:
        registry_id = registry_data.get("metadata", {}).get("id")
        if not registry_id:
            return

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

        try:
            with open(passport_path, "r", encoding="utf-8") as f:
                passport = json.load(f)
            passport_id = passport.get("citizenship", {}).get("registry_id")
        except Exception as exc:
            _record_passport_fault(passport_path, registry_path, exc)
            return
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


def _read_registry_json(registry_path: Path) -> Any:
    """Open and parse one registry file; every error is the caller's to name.

    A seam for tests: an OS-refused read is patched here, not on builtins.open.
    """
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_registry_data(registry_path: Path) -> Dict[str, Any]:
    """Read, parse, and normalize a registry file; no credential check, no logging."""
    if not registry_path.exists():
        raise RegistryNotFoundError(
            f"Registry not found at {registry_path}. Create a *_REGISTRY.json file in your project root."
        )

    try:
        data = _read_registry_json(registry_path)
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

    branches_raw = data["branches"]
    if isinstance(branches_raw, list):
        branches_dict: Dict[str, Any] = {}
        registry_dir = registry_path.parent
        for branch in branches_raw:
            name = branch.get("name", "").lower()
            if not name:
                continue
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
    """Return the registry in the AIPass home resolve_aipass_home() names, or None."""
    home = resolve_aipass_home().path
    if home is None:
        return None
    return _first_registry_in(home)


def load_registry() -> Dict[str, Any]:
    """Load the branch registry from disk."""
    registry_path = get_registry_path()
    data = _load_registry_data(registry_path)

    _verify_registry_credential(registry_path, data)

    branch_count = len(data.get("branches", {}))
    json_handler.log_operation("load_registry", {"path": str(registry_path), "branch_count": branch_count})

    return data


def _fleet_gateway() -> Any:
    """@memory's fleet gateway module, imported at CALL time and never at module level.

    A failure in @memory's import chain must cost the external tier, not every
    import of drone. A seam for tests: patched here, not on __import__.
    """
    from aipass.memory.apps.modules import fleet

    return fleet


def external_branches(repo_root: Optional[Path] = None) -> Optional[List[Dict[str, Any]]]:
    """Citizens in declared roots, in DECLARATION ORDER, as registry entries.

    None means the tier is LOST (no project root, or the gateway raised, logged
    at ERROR); [] means it answered and declares nobody.
    Never reads AIPASS_ROOTS.json itself: @memory's gateway is its one reader.
    ``name_from="registry"`` keys externals the way local branches are keyed.
    """
    # Scoped to the registry being resolved against, not this checkout; it is
    # also the seam that keeps the machine's declared roots out of tests.
    if repo_root is None:
        try:
            repo_root = get_registry_path().parent
        except Exception as exc:
            logger.warning("External tier: cannot locate a project root to scope declared roots: %s", exc)
            return None

    # The import sits inside the guard: @memory's registry_scope can raise at import
    # (ENOENT on a deleted cwd), and that must not take down drone.
    try:
        records = _fleet_gateway().external_branches(repo_root, name_from="registry")
    except Exception as exc:
        logger.error(
            "External tier unavailable — @memory's fleet gateway raised: %s. "
            "Local and AIPASS_HOME resolution continue; declared-root citizens do not resolve.",
            exc,
        )
        return None

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


def _external_branches(repo_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The lookups' view of the tier: a lost tier is no externals, never a crash."""
    tier = external_branches(repo_root)
    return [] if tier is None else tier


def _external_registry_path(entry: Dict[str, Any]) -> Optional[Path]:
    """The sealed registry an external entry was read from: the ancestor holding its registry filename."""
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

    Merges primary, then AIPass home, then declared roots; earlier wins a name collision.
    """
    merged: Dict[str, Any] = {}

    try:
        primary = load_registry()
        for name, branch in primary.get("branches", {}).items():
            merged[name] = branch
    except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
        logger.warning("get_all_branches: primary registry unavailable: %s", exc)

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

    # The one place both sides of a collision are visible, so the shadowing is named here.
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
    """Get a single branch by name (case-insensitive): primary, then AIPass home, then declared roots."""
    lower_name = name.lower()

    try:
        registry = load_registry()
        branch = registry.get("branches", {}).get(lower_name)
        if branch is not None:
            return branch
    except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
        logger.warning("get_branch_by_name: primary registry unavailable for '%s': %s", name, exc)

    home_path = _get_aipass_home_registry_path()
    primary_path = get_registry_path()
    if home_path is not None and home_path != primary_path:
        try:
            home_data = _load_registry_data(home_path)
            branch = home_data.get("branches", {}).get(lower_name)
            if branch is not None:
                return branch
            # A miss here is not an answer: returning it would hide the declared roots below.
        except (RegistryNotFoundError, RegistryCorruptError, RegistryPermissionError) as exc:
            logger.warning("get_branch_by_name: AIPass home registry unavailable for '%s': %s", name, exc)

    for entry in _external_branches():
        if entry["name"] == lower_name:
            logger.info("Resolved '%s' from declared root %s", lower_name, entry["registry"])
            return entry

    return None


def get_branch_with_registry(name: str) -> Optional[tuple]:
    """Get a branch and the registry path it was found in, in get_branch_by_name's order."""
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

    for entry in _external_branches():
        if entry["name"] == lower_name:
            external_registry = _external_registry_path(entry)
            if external_registry is None:
                continue
            logger.info("Resolved '%s' from declared root %s", lower_name, external_registry)
            return entry, external_registry

    return None
