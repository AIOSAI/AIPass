# =================== AIPass ====================
# Name: registry_handler.py
# Description: Handler for registry file operations
# Version: 1.4.0
# Created: 2026-03-09
# Modified: 2026-10-13
# =============================================

"""
Handler for registry file operations.

Handles loading, parsing, and normalizing *_REGISTRY.json files.
All file I/O and data transformation for the registry lives here.
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

#: The first passport the credential checks could not read, as the line main()
#: prints on stderr after routing. None while every passport read was clean.
_PASSPORT_FAULT: Optional[str] = None


def passport_fault() -> Optional[str]:
    """The line naming a passport the credential checks could not read, or None.

    Both checks accept the registry when the passport cannot be read (fleet
    green leg 7, drone's option C): refusing would send find_registry() to
    another project's registry with no word said. The fault is said instead,
    once, by drone.py main() on stderr after the command has run.
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

    Raises OSError or ValueError when the file cannot be read as the enrolment
    record: a fault to name, never "nothing enrolled".
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

    Order, first answer wins (@devpulse's brief, 2026-10-13):

    1. ``AIPASS_HOME`` set — an explicit setting beats a guess, used as given.
    2. The interpreter's own install: the installed ``drone`` runs on
       ``<home>/.venv/bin/python3``, so ``Path(sys.prefix).parent`` is the home
       when it holds an AIPASS_REGISTRY.json. A system Python or a tool venv
       fails that check and falls through.
    3. The homes enrolled in ``~/.aipass/trusted_projects.json``: the projects
       there that hold an AIPASS_REGISTRY.json, the newest ``enrolled`` first.
       (The prefer-the-interpreter's-parent rule is step 2 already: had that
       parent held a registry, step 2 would have answered.)

    A terminal opened before setup.sh wrote ``AIPASS_HOME`` into the shell rc
    still reaches the core branches through 2 or 3.

    Returns:
        AipassHome. ``path`` is None only when all three failed, and ``tried``
        then names each, so the tip can say what a person could act on.
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
    """``(homes, "")`` from the enrolment file, or ``([], why there are none)``.

    An unreadable file is a reason to print, never an empty enrolment: the
    tip names it, so a person can see which file to repair.
    """
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


# The homes whose interpreter choice this process has already logged: once per
# home, not once per routed command.
_ANNOUNCED_HOMES: set = set()


# Where a venv keeps its python, by platform: (directory, file name).
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

    A stranger's machine holds aipass twice: the uv tool venv whose ``drone``
    comes first on PATH, and the home's own ``.venv`` with the home's code
    installed editable. A home app run on the tool venv's python imports its
    handlers from the tool's site-packages, and the handlers fence refuses a
    caller outside its tree (the owner's sandbox, DPLAN-0408, 2026-10-13).

    * The branch is outside the resolved home (a project's own branch, a
      declared root), or no home resolved: ``sys.executable``, as always.
    * The home is ``Path(sys.prefix).parent``, so this drone IS the home's:
      ``sys.executable``.
    * Otherwise the home's own venv python when it exists, logged INFO once.
    * No venv there: ``sys.executable``, with a WARNING naming the home, once.
      setup.sh makes the venv; a home without one is half-installed.

    The venv path is returned as found, never resolved: a venv's python is a
    symlink to the base interpreter, and following it would lose the venv.
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
    """Return the first *_REGISTRY.json in *directory*, or None.

    When multiple matches exist, the alphabetically-first name wins
    so the result is deterministic across platforms.
    """
    matches = registries_in(directory)
    return matches[0] if matches else None


def _registry_matches_credential(registry_path: Path) -> bool:
    """Check whether a candidate registry matches the nearest passport.

    Returns True when the registry is acceptable (IDs match, either side is
    missing an ID, or the caller has no directory to walk from).  Returns False
    only when both IDs exist and disagree — the caller should skip this registry
    and keep walking.

    A registry it cannot read is accepted with a WARNING: load_registry() reads
    the same file and raises naming it. A passport it cannot read is accepted
    too, and recorded for passport_fault() so main() says it on stderr.

    DECLARED ROOTS DO NOT COME THROUGH HERE, AND THAT IS DELIBERATE.
    DECLARATION IS THE CREDENTIAL (@devpulse's ruling, FPLAN-0460 phase 3).
    This gate asks an INTRA-installation question — "are you a citizen of the
    registry you are standing in" — and a cross-repo answer is not available to
    it, because the ids differ BY CONSTRUCTION: AIPASS 7087bb93, VERA-STUDIO
    8fb38c96, WREN 9d11c395. Routing every external root through this check
    would refuse all of them, always, for being what they are.

    The authority a walk could never attach is the owner blessing
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
    except Exception as exc:
        # A fault of the REGISTRY is accepted: load_registry() reads the same
        # file and raises with its name. Skipping would resolve another
        # registry further up without a word.
        logger.warning("Credential pre-check could not read registry %s: %s", registry_path, exc)
        return True
    if not registry_id:
        return True

    cwd = caller_cwd()
    if cwd is None:
        # No location is not a failed check. The walk below infers from
        # where the caller STANDS, and a process whose directory was
        # deleted stands nowhere — the same answer as a walk that finds no
        # passport, reached honestly instead of through an except logging
        # "pre-check failed" for a check that did not fail.
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
        # A fault of the PASSPORT is accepted LOUDLY: refusing would send the
        # walk to another project's registry in silence. passport_fault()
        # carries it to main(), which says it once on stderr.
        _record_passport_fault(candidate, registry_path, exc)
        return True


def find_registry() -> Path:
    """Find a *_REGISTRY.json by walking up from this file's location.

    Search order:
    1. Explicitly set path via set_registry_path()
    2. AIPASS_REGISTRY environment variable
    3. Walk up from cwd (skipping registries that fail credential check)
    4. The AIPass home (resolve_aipass_home) — for external projects where CWD walk finds nothing
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

    # The AIPass home — AIPASS_HOME, else the interpreter's install, else an
    # enrolled home — for external projects where the CWD walk finds nothing
    hit = _get_aipass_home_registry_path()
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

        try:
            with open(passport_path, "r", encoding="utf-8") as f:
                passport = json.load(f)
            passport_id = passport.get("citizenship", {}).get("registry_id")
        except Exception as exc:
            # The same fault the pre-check records; said once, by main().
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


# ---------------------------------------------------------------------------
# Registry loading and querying
# ---------------------------------------------------------------------------


def _read_registry_json(registry_path: Path) -> Any:
    """Open and parse one registry file; every error is the caller's to name.

    The product has no reason of its own for this name; _load_registry_data
    could open inline. The reason is the test: a read the OS refuses is
    supplied here, not by replacing builtins.open for the whole process.
    """
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


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
    """Return the registry in the AIPass home resolve_aipass_home() names, or None."""
    home = resolve_aipass_home().path
    if home is None:
        return None
    return _first_registry_in(home)


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


def _fleet_gateway() -> Any:
    """@memory's fleet gateway module, imported at CALL time and never at module level.

    A failure anywhere in @memory's import chain must cost the external tier,
    not every import of drone (see external_branches, which calls this inside
    its guard). That call-time import is the product reason; it could sit
    inline in the guard. Its own name is for the test: a module that will not
    import is supplied here, not by replacing the interpreter's __import__ for
    the whole process.
    """
    from aipass.memory.apps.modules import fleet

    return fleet


def external_branches(repo_root: Optional[Path] = None) -> Optional[List[Dict[str, Any]]]:
    """Citizens in declared roots, in DECLARATION ORDER, as registry entries.

    Returns None when the tier is LOST (no project root to scope it, or the
    gateway raised), and [] when the tier answered and declares nobody. None is
    never a success answer, so a caller can tell the two apart; the lookups
    below read it through _external_branches, where a lost tier is no externals.

    Consumes @memory's public gateway and never reads AIPASS_ROOTS.json — the
    file has exactly one reader and it is theirs. A second reader here would be
    the two-implementations failure the gateway exists to prevent, and it would
    drift the first time their schema moved.

    Keyed the way local branches are: the registry's own ``name`` field,
    lowercased. ``name_from="registry"`` is not a preference — local resolution
    keys on that field (see _load_registry_data), and giving the external tier a
    different rule would mean ``@wren`` resolving by one law and ``@memory`` by
    another.

    Returns None and says so LOUDLY when the gateway fails. An empty declared-roots
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
    # enumeration test the moment the owner blessed the file. A third source with
    # no way to scope it is a third source that cannot be tested around.
    if repo_root is None:
        try:
            repo_root = get_registry_path().parent
        except Exception as exc:
            logger.warning("External tier: cannot locate a project root to scope declared roots: %s", exc)
            return None

    # Imported HERE, not at module level, and the import sits INSIDE the guard.
    # A module-level import made every failure in @memory's import chain a
    # failure to import drone — router, `drone rm`, `drone systems`, all of it —
    # which is the opposite of the containment this function's docstring
    # promises. The live instance: registry_scope.py runs
    # `REPO_ROOT = find_repo_root()` at module level and falls back to
    # Path.cwd() when the walk up from __file__ finds no AIPASS_REGISTRY.json.
    # A clean checkout has no registry (gitignored, machine-local), so CI takes
    # that fallback, and a process whose directory was deleted raises ENOENT
    # there. Theirs to fix; ours not to die of.
    #
    # sys.modules caches the module object, so this stays the SAME object the
    # suite patches with patch.object(fleet, ...) — a call-time import is not a
    # fresh one.
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
    """The lookups' view of the tier: a lost tier is no externals, never a crash.

    external_branches has already logged the loss at ERROR; local and
    AIPASS_HOME resolution go on without the declared roots.
    """
    tier = external_branches(repo_root)
    return [] if tier is None else tier


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
