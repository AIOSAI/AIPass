# =================== AIPass ====================
# Name: git_auth.py
# Description: Init handler — provision a project for manager-class git (owner-tier)
# Version: 1.0.0
# Created: 2026-08-04
# Modified: 2026-08-04
# =============================================

"""
Git-auth provisioning handler - PRIVATE implementation

Project-side counterpart to drone's owner-tier gate (DPLAN-0281). Drone grants
git write to a caller iff ALL FOUR of these hold:

  1. the caller's passport declares ``citizen_class: manager``
  2. tenancy — passport ``citizenship.registry_id`` == registry ``metadata.id``
  3. the project registry lists the caller with ``owner: true``
  4. path-binding — the passport is presented from at/under the registry-recorded
     path for that entry

This handler makes those four true for a consuming project, or refuses with an
error that names the exact fix. It repairs; it never guesses:

  - mints ``metadata.id`` when the registry has none
  - backfills the owner's passport ``citizenship.registry_id`` to match
  - flips the owner's ``citizen_class`` to ``manager``
  - writes ``owner: true`` onto the owner's registry entry, and records the
    owner's real branch directory as its path

GUARDRAIL (from @drone, non-negotiable): an owner entry must NEVER record the
repo root or a dot path. Path-binding is at-or-under, so a root path degrades
authority to repo-wide — any directory in the repo could then host a forged
passport and hold git. That case refuses instead of repairing.

Owner selection never guesses. The citizen the REGISTRY marks with
``owner: true`` IS the owner — the single source. With none marked, or more
than one, the run refuses and says what to add.

The passport-side ``citizenship.owner`` fallback retired with passport 2.0
(DPLAN-0319), which drops that field at migration; the refusal names the
retirement so a project that used to be seated by a passport claim is told why,
not just that nobody is marked. Registry-entry ``owner: true`` in
``*_REGISTRY.json`` is a DIFFERENT field and is unaffected.

RULES:
  - No CLI output — returns dicts, raises GitAuthRefusal; the module prints
  - Reads and writes go through json_handler (atomic write + fsync)
  - No hardcoded paths
"""

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

MANAGER_CLASS = "manager"

# Directories never worth walking when locating a citizen's branch directory.
_SKIP_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"})

# Depth cap for that walk — citizens live a few levels down (src/<pkg>/<name>),
# never at the bottom of a deep tree.
_MAX_SCAN_DEPTH = 6


class GitAuthRefusal(ValueError):
    """Provisioning cannot proceed honestly — message names the required fix."""


# =============================================================================
# JSON I/O
# =============================================================================


def _read_json(path: Path) -> Dict[str, Any]:
    """Read a JSON object from *path*, raising GitAuthRefusal on bad content."""
    data = json_handler.load_path(path)
    if not isinstance(data, dict):
        raise GitAuthRefusal(f"{path} could not be read as a JSON object — fix or restore the file, then re-run")
    return data


def _read_passport(path: Path) -> Optional[Dict[str, Any]]:
    """Read a passport, or None when it is missing or unreadable.

    Used by the scans, where one unreadable passport must not sink the run —
    the owner's own passport is read with ``_read_json`` and does refuse.
    """
    if not path.is_file():
        return None
    data = json_handler.load_path(path)
    if not isinstance(data, dict):
        logger.warning("[git-auth] Passport at %s is not readable JSON — skipping", path)
        return None
    return data


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    """Write *data* to *path* atomically, refusing loudly if the write fails.

    A half-written registry locks every citizen out of its own project, so the
    file is only ever swapped in complete — and a failed write is never
    reported as a repair.
    """
    if not json_handler.save_path(path, data):
        raise GitAuthRefusal(f"{path} could not be written — check file permissions, then re-run")


# =============================================================================
# Registry + passport reading
# =============================================================================


def find_registry(target: Path) -> Optional[Path]:
    """Walk up from *target* for a ``*_REGISTRY.json``; None when there is none.

    Matches drone's discovery: the glob convention (``VERA-STUDIO_REGISTRY.json``)
    and sorted-first so a directory holding two registries resolves the same way
    on every platform.
    """
    current = target.resolve()
    for candidate in [current, *current.parents]:
        matches = sorted(candidate.glob("*_REGISTRY.json"))
        if matches:
            return matches[0]
    return None


def _entries(registry_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return branch entries as a list of live dicts (both registry shapes).

    Registries are authored as a list of objects or as a name-keyed dict. The
    dicts inside are returned by reference, so mutating one here mutates what
    gets written back — the file's own shape is preserved, never reshaped.
    """
    branches = registry_data.get("branches", [])
    if isinstance(branches, dict):
        found = []
        for key, entry in branches.items():
            if isinstance(entry, dict):
                entry.setdefault("name", key)
                found.append(entry)
        return found
    return [entry for entry in branches if isinstance(entry, dict)]


def _citizen_class(passport: Dict[str, Any]) -> str:
    """Read citizen_class from either passport layout, '' when absent."""
    identity = passport.get("identity", {})
    branch_info = passport.get("branch_info", {})
    return identity.get("citizen_class") or branch_info.get("citizen_class") or ""


def _resolved_path(entry: Dict[str, Any], repo_root: Path) -> Optional[Path]:
    """Resolve an entry's recorded path against the repo root, None when unset.

    Relative paths resolve against the repo root — never CWD, which would bind
    authority to wherever the user happened to be standing.
    """
    raw = entry.get("path")
    if not raw or not str(raw).strip():
        return None
    recorded = Path(str(raw))
    if not recorded.is_absolute():
        recorded = repo_root / recorded
    try:
        return recorded.resolve()
    except OSError as exc:
        logger.warning("Registry path %s could not be resolved: %s", recorded, exc)
        return None


def _locate_branch_dir(repo_root: Path, name: str) -> Optional[Path]:
    """Find the citizen's real branch directory by its passport, or None.

    Used only when the registry records no path at all. The repo root is never
    a candidate — a root-level passport would mean root-level path-binding,
    which is exactly what the guardrail exists to prevent.
    """
    wanted = name.lower()
    root_depth = len(repo_root.parts)
    for dirpath, dirnames, _filenames in os.walk(repo_root):
        current = Path(dirpath)
        if len(current.parts) - root_depth >= _MAX_SCAN_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if current == repo_root:
            continue
        passport = _read_passport(current / ".trinity" / "passport.json")
        if passport is None:
            continue
        branch_name = passport.get("branch_info", {}).get("branch_name") or passport.get("identity", {}).get("name")
        if str(branch_name or "").lower() == wanted:
            return current.resolve()
    return None


# =============================================================================
# Owner selection — marked, never guessed
# =============================================================================


def _select_owner(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the owner entry. Refuses rather than guessing.

    The registry's own ``owner: true`` is the ONLY source. The passport-side
    ``citizenship.owner`` fallback that used to run here retired with passport
    2.0 (DPLAN-0319): the migration DROPS that field, so consulting it would be
    reading a key no current passport carries — a branch that can only ever go
    dead-silent, turning "the rule changed" into "nobody is marked".

    Which is why the no-owner refusal below NAMES the retirement. A project
    that used to be seated off a passport claim otherwise gets a message that
    is true but unhelpful, and no way to learn why yesterday's setup stopped
    working. Loud beats silent even when the silence is technically correct.
    """
    flagged = [entry for entry in entries if entry.get("owner") is True]
    if len(flagged) == 1:
        return flagged[0]
    if len(flagged) > 1:
        names = ", ".join(sorted(str(entry.get("name", "?")) for entry in flagged))
        raise GitAuthRefusal(
            f"more than one citizen is marked owner: true ({names}) — owner-tier binds to exactly one "
            "citizen, so remove owner: true from every entry except the project owner, then re-run"
        )

    listed = ", ".join(sorted(str(entry.get("name", "?")) for entry in entries)) or "(no citizens listed)"
    raise GitAuthRefusal(
        'no citizen is marked as the project owner, and this never guesses — add "owner": true to the '
        f"owning citizen's entry in the registry, then re-run. Citizens listed: {listed}. "
        "(A passport's citizenship.owner is no longer consulted: passport 2.0 dropped that field, "
        "so the registry entry is now the only source of truth for ownership.)"
    )


# =============================================================================
# Independent verification — re-read from disk, never trust the repair's own count
# =============================================================================


def verify_git_auth(registry_path: Path, owner_name: str) -> List[str]:
    """Re-check drone's four conditions from disk; return the failures.

    Deliberately independent of the repair pass: it re-reads both files and
    re-derives every answer, so a repair that reported success but wrote the
    wrong thing still shows up as a failure here.
    """
    failures: List[str] = []
    try:
        registry_data = _read_json(registry_path)
    except GitAuthRefusal as exc:
        logger.warning("[git-auth] Verification could not read registry %s: %s", registry_path, exc)
        return [str(exc)]

    repo_root = registry_path.parent.resolve()
    entry = next(
        (e for e in _entries(registry_data) if str(e.get("name", "")).lower() == owner_name.lower()),
        None,
    )
    if entry is None:
        return [f"check 3 (owner flag): '{owner_name}' is not listed in {registry_path.name}"]

    registry_id = registry_data.get("metadata", {}).get("id")
    if not registry_id:
        failures.append(f"check 2 (tenancy): {registry_path.name} still declares no metadata.id")
    if entry.get("owner") is not True:
        failures.append(f"check 3 (owner flag): entry for '{owner_name}' is not marked owner: true")

    branch_dir = _resolved_path(entry, repo_root)
    if branch_dir is None:
        failures.append(f"check 4 (path-binding): entry for '{owner_name}' records no path")
        return failures
    if branch_dir == repo_root:
        failures.append(f"check 4 (path-binding): entry for '{owner_name}' records the repo root")
        return failures

    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.is_file():
        failures.append(f"check 1 (manager class): no passport at {passport_path}")
        return failures
    try:
        passport = _read_json(passport_path)
    except GitAuthRefusal as exc:
        logger.warning("[git-auth] Verification could not read passport %s: %s", passport_path, exc)
        failures.append(str(exc))
        return failures

    if _citizen_class(passport) != MANAGER_CLASS:
        failures.append(
            f"check 1 (manager class): '{owner_name}' is citizen_class "
            f"'{_citizen_class(passport) or 'unset'}', not '{MANAGER_CLASS}'"
        )
    passport_id = passport.get("citizenship", {}).get("registry_id")
    if registry_id and passport_id != registry_id:
        failures.append(
            f"check 2 (tenancy): '{owner_name}' passport registry_id "
            f"{passport_id or '(unset)'} != registry metadata.id {registry_id}"
        )
    return failures


# =============================================================================
# Public entry point
# =============================================================================


def provision_git_auth(target: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Provision or repair *target* so its owner citizen can hold git.

    Plans every repair before writing anything, so a run that must refuse
    (root path, no marked owner, missing passport) leaves the project exactly
    as it found it rather than half-provisioned.

    Args:
        target: A directory inside the project (the registry is found upward).
        dry_run: Plan and report the repairs without writing them.

    Returns:
        dict with ``registry``, ``owner``, ``repairs``, ``already_ok``,
        ``verified``, ``verify_failures``, ``dry_run``.

    Raises:
        GitAuthRefusal: The four conditions cannot be made true honestly. The
            message names what a human must add or correct.
    """
    registry_path = find_registry(Path(target))
    if registry_path is None:
        raise GitAuthRefusal(
            f"no *_REGISTRY.json found at or above {Path(target).resolve()} — "
            "this is not an AIPass project; run 'aipass init' first"
        )

    repo_root = registry_path.parent.resolve()
    registry_data = _read_json(registry_path)
    entries = _entries(registry_data)

    owner_entry = _select_owner(entries)
    owner_name = str(owner_entry.get("name", "?"))

    repairs: List[str] = []
    already_ok: List[str] = []
    registry_dirty = False

    # --- check 3: owner: true on the registry entry ---
    # Never a repair any more: the registry flag is the only way to reach here,
    # so the alternative is the named refusal in _select_owner, not a backfill.
    already_ok.append(f"registry: '{owner_name}' already marked owner: true")

    # --- check 2 (registry half): metadata.id ---
    registry_id = registry_data.get("metadata", {}).get("id")
    if not registry_id:
        registry_id = str(uuid.uuid4())
        registry_data.setdefault("metadata", {})["id"] = registry_id
        registry_dirty = True
        repairs.append(f"registry: minted metadata.id {registry_id}")
    else:
        already_ok.append(f"registry: metadata.id already set ({registry_id})")

    # --- check 4: path-binding, with the never-a-root-path guardrail ---
    raw_path = owner_entry.get("path")
    branch_dir = _resolved_path(owner_entry, repo_root)
    if branch_dir is not None and branch_dir == repo_root:
        raise GitAuthRefusal(
            f"registry entry for '{owner_name}' records path '{raw_path}', which is the project root "
            f"({repo_root}). Path-binding is at-or-under, so a root path would let a passport placed "
            "ANYWHERE in this repo hold git. Record the citizen's own branch directory instead "
            f"(for example 'src/<package>/{owner_name.lower()}'), then re-run"
        )

    if branch_dir is None:
        located = _locate_branch_dir(repo_root, owner_name)
        if located is None:
            raise GitAuthRefusal(
                f"registry entry for '{owner_name}' records no path, and no directory under {repo_root} "
                'holds a passport with that branch_name — add "path" pointing at the citizen\'s own '
                "branch directory (never the repo root), then re-run"
            )
        try:
            recorded = located.relative_to(repo_root).as_posix()
        except ValueError as exc:
            # Symlinked citizen dir that resolves outside the root — record the
            # absolute path so path-binding still has something exact to compare.
            logger.info("[git-auth] %s is not under %s (%s) — recording absolute path", located, repo_root, exc)
            recorded = str(located)
        owner_entry["path"] = recorded
        branch_dir = located
        registry_dirty = True
        repairs.append(f"registry: recorded path '{recorded}' for '{owner_name}' (found by its passport)")
    else:
        if repo_root not in branch_dir.parents:
            raise GitAuthRefusal(
                f"registry entry for '{owner_name}' records path '{raw_path}', which resolves outside the "
                f"project ({branch_dir}). Path-binding compares against the passport's own directory inside "
                "this repo, so an outside path can never match. Record the citizen's branch directory "
                "relative to the project root, then re-run"
            )
        if not branch_dir.is_dir():
            raise GitAuthRefusal(
                f"registry entry for '{owner_name}' records path '{raw_path}', but {branch_dir} does not "
                "exist. Correct the path to the citizen's real branch directory, then re-run"
            )
        already_ok.append(f"registry: '{owner_name}' path already bound to {branch_dir}")

    # --- checks 1 + 2 (passport half) ---
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.is_file():
        raise GitAuthRefusal(
            f"'{owner_name}' has no passport at {passport_path} — an owner entry must point at a real "
            "citizen directory. Create the citizen (drone @spawn create <path>) or correct the entry's "
            "path, then re-run"
        )

    passport = _read_json(passport_path)
    passport_dirty = False

    current_class = _citizen_class(passport)
    if current_class != MANAGER_CLASS:
        passport.setdefault("identity", {})["citizen_class"] = MANAGER_CLASS
        # Older passports carry the class under branch_info too. Drone reads
        # identity first, but a stale second copy is a trap for the next reader.
        if "citizen_class" in passport.get("branch_info", {}):
            passport["branch_info"]["citizen_class"] = MANAGER_CLASS
        passport_dirty = True
        repairs.append(f"passport: '{owner_name}' citizen_class {current_class or '(unset)'} → {MANAGER_CLASS}")
    else:
        already_ok.append(f"passport: '{owner_name}' already citizen_class {MANAGER_CLASS}")

    passport_id = passport.get("citizenship", {}).get("registry_id")
    if passport_id != registry_id:
        passport.setdefault("citizenship", {})["registry_id"] = registry_id
        passport_dirty = True
        repairs.append(f"passport: '{owner_name}' citizenship.registry_id {passport_id or '(unset)'} → {registry_id}")
    else:
        already_ok.append(f"passport: '{owner_name}' tenancy already matches metadata.id")

    # --- apply ---
    if not dry_run:
        if registry_dirty:
            _write_json(registry_path, registry_data)
            logger.info("[git-auth] Registry %s updated for owner %s", registry_path.name, owner_name)
        if passport_dirty:
            _write_json(passport_path, passport)
            logger.info("[git-auth] Passport for %s updated", owner_name)

    verify_failures = [] if dry_run else verify_git_auth(registry_path, owner_name)
    if verify_failures:
        logger.warning("[git-auth] Verification failed after repair: %s", "; ".join(verify_failures))

    # Granting a citizen git write is worth an audit trail — who, where, and
    # exactly what was changed to make it true.
    json_handler.log_operation(
        "git_auth_provision",
        {
            "registry": str(registry_path),
            "owner": owner_name,
            "owner_path": str(branch_dir),
            "repairs": repairs,
            "verify_failures": verify_failures,
            "dry_run": dry_run,
        },
    )

    return {
        "registry": str(registry_path),
        "repo_root": str(repo_root),
        "owner": owner_name,
        "owner_path": str(branch_dir),
        "repairs": repairs,
        "already_ok": already_ok,
        "verified": (not verify_failures) if not dry_run else None,
        "verify_failures": verify_failures,
        "dry_run": dry_run,
    }
