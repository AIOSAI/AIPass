# =================== AIPass ====================
# Name: registry.py
# Description: *_REGISTRY.json discovery and CRUD operations
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-06-10
# =============================================

"""*_REGISTRY.json discovery and CRUD operations.

Identity model (DPLAN-0239, settled 2026-07-11):

  registry.metadata.id
      PROJECT credential — authoritative, minted once at ``aipass init``.
      Passport ``citizenship.registry_id`` conforms to it (drone enforces
      the pair at routing time). Spawn never mints this; bootstrap.py does.

  branch-entry registry_id
      PER-CITIZEN UUID — set-once, minted by ``add_to_registry`` at entry
      creation. Uniquely identifies the citizen *within* the project.
      NOT the project credential; NOT copied from the passport.

  owner (entry field, ``True`` / absent)
      Sealed authority flag. First agent = project owner.  Seated via
      ``ensure_project_has_owner`` at creation time. ``citizen_class ==
      'manager'`` is a cosmetic preference for the seating heuristic,
      never the gate — the entry ``owner: true`` IS the gate.

  admin (entry field, ``True`` / absent) — DPLAN-0288
      One seat only: devpulse. Written by ``ensure_admin`` (the sanctioned
      path, exposed as ``drone @spawn grant-admin``) during Patrick's
      ceremony. This flag on its own GRANTS NOTHING — it is leg 5 of a
      five-leg contract (verified caller, cert path, cert content, HMAC
      signature, this flag); the lane stays dark unless all five pass.
"""

import sys
import uuid
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.json import json_handler


_PROTECTED_FLOOR = frozenset({"spawn", "devpulse", "drone"})

# The one seat that may ever carry the registry admin flag (DPLAN-0288).
# A constant, never a caller-chosen parameter — see ensure_admin().
ADMIN_BRANCH = "devpulse"


def is_protected(branch_name, branch_dir=None, registry_path=None):
    """Check if a branch is protected from deletion and pollution cleanup.

    Protection layers (any one is sufficient):
      1. Hardcoded floor — spawn, devpulse, drone.
      2. Registry owner flag — entry has ``owner: true``.
      3. Active passport — ``.trinity/passport.json`` with
         ``citizenship.registered == True``.

    Args:
        branch_name: Branch name to check (case-insensitive).
        branch_dir: Path to the branch directory (for passport check).
            Auto-resolved from registry when omitted.
        registry_path: Path to ``*_REGISTRY.json``.
            Auto-discovered via ``find_registry()`` when omitted.

    Returns:
        Tuple of (protected: bool, reason: str).
    """
    name_lower = branch_name.lower()

    if name_lower in _PROTECTED_FLOOR:
        return True, f"infrastructure ({', '.join(sorted(_PROTECTED_FLOOR))})"

    try:
        rp = Path(registry_path) if registry_path else find_registry()
        reg_data = load_registry(rp)
        for entry in branches_as_list(reg_data.get("branches", [])):
            if entry.get("name", "").lower() == name_lower:
                if entry.get("owner") is True:
                    return True, "registry owner"
                if branch_dir is None:
                    branch_dir = (rp.parent / entry.get("path", "")).resolve()
                break
    except (OSError, ValueError, KeyError) as exc:
        logger.info("[is_protected] Registry lookup failed for %s: %s", branch_name, exc)

    if branch_dir is not None:
        passport_path = Path(branch_dir) / ".trinity" / "passport.json"
        if passport_path.is_file():
            try:
                passport = json_handler.read_json(passport_path)
                if passport and passport.get("citizenship", {}).get("registered") is True:
                    return True, "active citizen"
            except (OSError, ValueError, KeyError) as exc:
                logger.info("[is_protected] Passport read failed for %s: %s", branch_name, exc)

    return False, ""


def branches_as_list(branches):
    """Normalize branches to a list regardless of storage format.

    The registry may store branches as:
    - A list of dicts (legacy format)
    - A dict keyed by name (dict format from setup.sh)

    Returns:
        list of branch entry dicts
    """
    if isinstance(branches, dict):
        return list(branches.values())
    if isinstance(branches, list):
        return branches
    return []


def find_registry(start_path=None):
    """Find *_REGISTRY.json — walks up from start_path only.

    Does NOT pass package_root — prevents silent registration in
    AIPass's own registry when creating agents in external projects.

    Args:
        start_path: Directory to start searching from.

    Returns:
        Path to *_REGISTRY.json.
    """
    from aipass.aipass.shared.registry_discovery import find_registry as _common_find

    return _common_find(start_path=start_path)


def load_registry(registry_path):
    """
    Load registry from JSON file. Returns empty schema if missing.

    Args:
        registry_path: Path to AIPASS_REGISTRY.json

    Returns:
        Dict with metadata and branches list
    """
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return {
            "metadata": {
                "version": "1.0.0",
                "last_updated": datetime.now().strftime("%Y-%m-%d"),
                "total_branches": 0,
            },
            "branches": [],
        }

    data = json_handler.read_json(registry_path)
    if data is not None:
        return data
    return {
        "metadata": {
            "version": "1.0.0",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "total_branches": 0,
        },
        "branches": [],
    }


def save_registry(registry_path, data):
    """
    Save registry to JSON file. Auto-updates timestamp and sorts branches.

    Args:
        registry_path: Path to AIPASS_REGISTRY.json
        data: Registry dict to save

    Returns:
        True on success, False on error
    """
    registry_path = Path(registry_path)
    data["metadata"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")

    if "branches" in data:
        branches = data["branches"]
        if isinstance(branches, dict):
            branch_list = list(branches.values())
        else:
            branch_list = branches
        data["branches"] = sorted(branch_list, key=lambda b: b.get("name", ""))

    return json_handler.write_json(registry_path, data)


def get_next_citizen_number(registry_path):
    """Get next citizen number from registry (count of existing branches + 1).

    Args:
        registry_path: Path to AIPASS_REGISTRY.json

    Returns:
        int: Next citizen number
    """
    data = load_registry(registry_path)
    branches = data.get("branches", [])
    return len(branches_as_list(branches)) + 1


def _validate_path_containment(branch_path, registry_path):
    """Reject paths that escape the project root (directory containing the registry)."""
    registry_root = Path(registry_path).resolve().parent
    bp = Path(branch_path)
    resolved = (registry_root / bp).resolve() if not bp.is_absolute() else bp.resolve()
    try:
        resolved.relative_to(registry_root)
        return True
    except ValueError:
        logger.warning("[registry] Path %s is outside project root %s", resolved, registry_root)
        return False


def add_to_registry(registry_path, branch_name, branch_path, profile, email, purpose="", citizen_id=""):
    """Add a new branch entry to the registry.

    Mints a fresh per-citizen UUID for the entry's ``registry_id`` (the citizen
    UID) unless the caller supplies one.  This is NOT the project credential —
    that lives in ``metadata.id`` and is copied into passports separately.

    ``citizen_id`` exists so a caller that has ALREADY stamped the id into the
    citizen's passport can hand the same value here: the passport's
    ``citizenship.citizen_id`` and this entry's ``registry_id`` are two copies
    of one fact, and minting twice would silently produce two different ids for
    the same citizen.  Callers with no passport to match (adoption) omit it.

    Uses file locking around the entire read-modify-write cycle to prevent
    corruption from concurrent spawns. Skips locking on Windows.

    Args:
        registry_path: Path to AIPASS_REGISTRY.json
        branch_name: Uppercase branch name (e.g. "MY_AGENT")
        branch_path: Absolute path to branch directory
        profile: Profile string (e.g. "AIPass Workshop")
        email: Branch email (e.g. "@my_agent")
        purpose: Optional purpose description
        citizen_id: Optional pre-minted per-citizen UUID. Empty string mints a
            fresh one, which is the correct behaviour when no passport carries
            the id yet.

    Returns:
        True if added, False if already exists or error
    """
    registry_path = Path(registry_path)

    if not _validate_path_containment(branch_path, registry_path):
        logger.error("[registry] Path containment violation: %s escapes project root", branch_path)
        return False

    lock_path = registry_path.parent / f".{registry_path.stem}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        lock_fd = None
    else:
        import fcntl

        lock_fd = open(lock_path, "w", encoding="utf-8")  # noqa: SIM115
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

    try:
        registry = load_registry(registry_path)
        branches = registry.get("branches", [])

        if isinstance(branches, dict):
            if branch_name in branches:
                return False
        else:
            for branch in branches:
                if branch.get("name") == branch_name:
                    return False

        today = datetime.now().strftime("%Y-%m-%d")
        entry = {
            "name": branch_name,
            "path": Path(branch_path).as_posix(),
            "profile": profile,
            "description": purpose or "New agent - purpose TBD",
            "email": email,
            "status": "active",
            "created": today,
            "last_active": today,
            "registry_id": citizen_id or str(uuid.uuid4()),
        }

        if isinstance(branches, dict):
            branches[branch_name] = entry
        else:
            branches.append(entry)
        registry["branches"] = branches
        registry["metadata"]["total_branches"] = len(branches_as_list(branches))

        json_handler.log_operation("registry_updated", data={"branch": branch_name})

        return save_registry(registry_path, registry)
    finally:
        if lock_fd is not None and sys.platform != "win32":
            import fcntl

            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def fix_passport_registry_id(branch_dir: Path, registry_path: Path) -> bool:
    """Update passport.json registry_id if it doesn't match the current registry.

    Call when adopting an existing agent or during sync-registry --fix to repair
    registry_id mismatches caused by registry recreation.

    Args:
        branch_dir: Path to the branch directory (containing .trinity/passport.json)
        registry_path: Path to the project registry (*_REGISTRY.json)

    Returns:
        True if passport was updated, False if already correct or failed.
    """
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        return False
    if not registry_path.exists():
        return False

    try:
        registry_data = json_handler.read_json(registry_path)
        if registry_data is None:
            return False
        current_id = registry_data.get("metadata", {}).get("id", "")
    except Exception as e:
        logger.warning("[registry] Cannot read registry_id from %s: %s", registry_path.name, e)
        return False

    if not current_id:
        return False

    try:
        passport = json_handler.read_json(passport_path)
        if passport is None:
            return False
        old_id = passport.get("citizenship", {}).get("registry_id", "")
        if old_id == current_id:
            return False  # Already correct, no update needed

        passport.setdefault("citizenship", {})["registry_id"] = current_id
        success = json_handler.write_json(passport_path, passport)
        if success:
            logger.info(
                "[registry] Fixed registry_id for %s: %s → %s",
                branch_dir.name,
                old_id[:8] if old_id else "empty",
                current_id[:8],
            )
        return success
    except Exception as e:
        logger.warning("[registry] Failed to fix registry_id for %s: %s", branch_dir.name, e)
        return False


def pick_owner_branch(branches, project_root):
    """Select which branch entry should be the owner (no writes).

    Canonical heuristic (first match wins):
      1. citizen_class == "manager" (cosmetic preference, not the gate)
      2. passport citizenship.owner == true
      3. First agent by ``created`` date (ultimate fallback)

    Args:
        branches: List of branch entry dicts.
        project_root: Path to the project root (registry parent dir).

    Returns:
        The chosen branch entry dict, or None if branches is empty.
    """
    if not branches:
        return None

    project_root = Path(project_root)

    for branch in branches:
        branch_path = project_root / branch.get("path", "")
        passport_path = branch_path / ".trinity" / "passport.json"
        if passport_path.exists():
            passport = json_handler.read_json(passport_path)
            if passport and passport.get("identity", {}).get("citizen_class") == "manager":
                return branch

    for branch in branches:
        branch_path = project_root / branch.get("path", "")
        passport_path = branch_path / ".trinity" / "passport.json"
        if passport_path.exists():
            passport = json_handler.read_json(passport_path)
            if passport and passport.get("citizenship", {}).get("owner") is True:
                return branch

    return min(branches, key=lambda b: b.get("created", "9999-99-99"))


def ensure_project_has_owner(registry_path):
    """Ensure exactly one branch entry in the registry has owner:true.

    Uses ``pick_owner_branch`` for the canonical seating heuristic.
    Writes to the REGISTRY ENTRY (sealed authority), not the passport.
    """
    registry_path = Path(registry_path)
    reg_data = load_registry(registry_path)
    branches = branches_as_list(reg_data.get("branches", []))
    if not branches:
        return False

    for branch in branches:
        if branch.get("owner") is True:
            return False

    owner_branch = pick_owner_branch(branches, registry_path.parent)
    if owner_branch is None:
        return False

    owner_branch["owner"] = True
    save_registry(registry_path, reg_data)
    logger.info("[registry] Set owner=true on %s (registry entry)", owner_branch.get("name", "?"))
    return True


def ensure_admin(registry_path=None, branch_name=ADMIN_BRANCH):
    """Set ``admin: true`` on the devpulse entry of the root registry.

    The sanctioned write path for Patrick's admin ceremony (DPLAN-0288),
    mirroring ``ensure_project_has_owner``: authority is written to the
    REGISTRY ENTRY, never to a passport a branch can edit on itself.

    HARD FENCE: ``branch_name`` exists so the refusal is testable, not so
    callers can choose a seat. Anything other than ``ADMIN_BRANCH`` is
    refused by name — this helper can never grant admin to anyone else.

    The flag alone grants NOTHING: the admin dispatch lane verifies five
    legs (verified caller, cert path, cert content, signature, this flag).

    Args:
        registry_path: Path to the root ``AIPASS_REGISTRY.json``.
            Auto-discovered via ``find_registry()`` when omitted.
        branch_name: Must be devpulse (case-insensitive). Anything else refuses.

    Returns:
        Tuple of (status, reason) where status is one of:
            "granted"  — flag newly written
            "already"  — flag was already true, nothing written
            "refused"  — nothing written, reason names why
    """
    requested = (branch_name or "").strip().lower()
    if requested != ADMIN_BRANCH:
        reason = (
            f"REFUSED: admin is a {ADMIN_BRANCH}-only privilege — "
            f"ensure_admin cannot grant it to '{branch_name or '(empty)'}'. "
            "The seat is a constant, not a parameter."
        )
        logger.warning("[registry] %s", reason)
        return "refused", reason

    registry_path = Path(registry_path) if registry_path else find_registry()
    reg_data = load_registry(registry_path)
    branches = branches_as_list(reg_data.get("branches", []))

    for branch in branches:
        if branch.get("name", "").lower() != ADMIN_BRANCH:
            continue
        if branch.get("admin") is True:
            reason = f"{ADMIN_BRANCH} entry already carries admin:true in {registry_path.name}"
            logger.info("[registry] %s", reason)
            return "already", reason
        branch["admin"] = True
        save_registry(registry_path, reg_data)
        reason = f"Granted admin:true to the {ADMIN_BRANCH} entry in {registry_path.name}"
        logger.info("[registry] %s", reason)
        json_handler.log_operation("admin_granted", data={"branch": ADMIN_BRANCH})
        return "granted", reason

    reason = f"REFUSED: no {ADMIN_BRANCH} entry in {registry_path} — nothing written"
    logger.warning("[registry] %s", reason)
    return "refused", reason


def backfill_owner_and_registry_id(registry_path):
    """Backfill owner and per-citizen registry_id into branch entries.

    Mints a fresh UUID for any entry that is missing ``registry_id`` or
    holds a stale project-id duplicate (same value as another entry).
    Already-unique UUIDs are never touched.

    Also seats owner via ``ensure_project_has_owner`` if missing.
    """
    registry_path = Path(registry_path)
    reg_data = load_registry(registry_path)
    branches = branches_as_list(reg_data.get("branches", []))
    if not branches:
        return False

    changed = False

    seen_ids: dict[str, int] = {}
    for branch in branches:
        rid = branch.get("registry_id", "")
        if rid:
            seen_ids[rid] = seen_ids.get(rid, 0) + 1

    for branch in branches:
        rid = branch.get("registry_id", "")
        if not rid or seen_ids.get(rid, 0) > 1:
            branch["registry_id"] = str(uuid.uuid4())
            changed = True

    if changed:
        save_registry(registry_path, reg_data)
        logger.info("[registry] Backfilled per-citizen registry_id into entries")

    owner_seated = ensure_project_has_owner(registry_path)
    return changed or owner_seated


def get_owner(start_path=None):
    """Return the branch entry dict whose owner==true, or None.

    Walks up from start_path (default CWD) to find *_REGISTRY.json.
    """
    registry_path = find_registry(start_path=start_path)
    if not registry_path.exists():
        return None
    reg_data = load_registry(registry_path)
    for branch in branches_as_list(reg_data.get("branches", [])):
        if branch.get("owner") is True:
            return branch
    return None


def is_owner(email, start_path=None):
    """True iff email matches the owner entry's email.

    Normalizes email — tolerates with/without leading '@'.
    """
    if not email:
        return False
    normalized = (email if email.startswith("@") else f"@{email}").lower()
    owner = get_owner(start_path=start_path)
    if owner is None:
        return False
    owner_email = owner.get("email", "")
    owner_normalized = (owner_email if owner_email.startswith("@") else f"@{owner_email}").lower()
    return normalized == owner_normalized
