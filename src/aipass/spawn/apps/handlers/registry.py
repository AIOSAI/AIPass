# =================== AIPass ====================
# Name: registry.py
# Description: *_REGISTRY.json discovery and CRUD operations
# Version: 1.1.0
# Created: 2026-03-05
# Modified: 2026-10-18
# =============================================

"""*_REGISTRY.json discovery and CRUD operations.

metadata.id is the project credential; an entry's registry_id is a per-citizen UUID. Never conflate them.
Entry flags owner and admin are the sealed authority; a passport never is."""

import uuid
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.spawn.apps.handlers.json import json_handler

# POSIX only: Windows has no fcntl, so add_to_registry takes no lock there.
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]
    logger.info("[registry] fcntl unavailable (Windows) — add_to_registry runs unlocked")


_PROTECTED_FLOOR = frozenset({"spawn", "devpulse", "drone"})

# The one seat that may ever carry the registry admin flag: a constant, never a parameter.
ADMIN_BRANCH = "devpulse"


def is_protected(branch_name, branch_dir=None, registry_path=None, count_passport=True):
    """Check if a branch is protected from deletion and pollution cleanup.

    Any one layer protects: the hardcoded floor, the registry owner flag, or a registered passport.
    count_passport=False asks the floor and owner layers only (retirement clears the passport layer).
    Returns (protected, reason)."""
    name_lower = branch_name.lower()

    if name_lower in _PROTECTED_FLOOR:
        return True, f"infrastructure ({', '.join(sorted(_PROTECTED_FLOOR))})"

    try:
        rp = Path(registry_path) if registry_path else find_registry()
        if rp is None:
            # Answer, never raise: AttributeError on None would escape the except below inside a safety check.
            logger.info("[is_protected] No registry found — registry layer cannot answer for %s", branch_name)
            return False, "no registry found — not protected by the registry layer"
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

    if count_passport and branch_dir is not None:
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
    """Normalize branches to a list regardless of storage format (list, or dict keyed by name)."""
    if isinstance(branches, dict):
        return list(branches.values())
    if isinstance(branches, list):
        return branches
    return []


def find_registry(start_path=None):
    """Find *_REGISTRY.json — walks up from start_path only.

    No package_root fallback: it would silently register external agents in AIPass's own registry.
    Returns None when no registry is found."""
    from aipass.aipass.shared.registry_discovery import find_registry as _common_find

    return _common_find(start_path=start_path)


def _default_registry_schema(credential=""):
    """Return an empty registry document; an empty credential omits metadata.id, it never mints one."""
    metadata = {
        "version": "1.0.0",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "total_branches": 0,
    }
    if credential:
        metadata["id"] = credential
    return {"metadata": metadata, "branches": []}


def load_registry(registry_path):
    """Load registry from JSON file; an empty schema with no metadata.id when missing or unreadable.

    Loading is a read: it never mints a credential. Minting is resolve_project_credential's decision;
    inventing one for an unreadable file would re-credential a live project and orphan its passports."""
    registry_path = Path(registry_path)
    if not registry_path.exists():
        logger.info(
            "[registry] %s does not exist — returning an empty document with NO credential. "
            "A project credential is minted only by resolve_project_credential(), never by a load.",
            registry_path,
        )
        return _default_registry_schema()

    data = json_handler.read_json(registry_path)
    if data is not None:
        return data

    logger.warning(
        "[registry] %s exists but could not be read — returning an empty schema WITHOUT a credential "
        "so a live project is never re-credentialled. Its branches are not in this result.",
        registry_path.name,
    )
    return _default_registry_schema()


def registry_is_writable_document(registry_path) -> bool:
    """Is this registry safe to run a read-modify-write cycle against?

    True when missing (nothing to lose) or a JSON object; False when it exists but is unreadable.
    load_registry answers both with an empty document, and writing that wipes every live branch."""
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return True

    data = json_handler.read_json(registry_path)
    return isinstance(data, dict)


def resolve_project_credential(registry_path) -> str:
    """Return the project credential to stamp on a citizen being created here.

    The explicit mint; call only when creating a citizen. Absent registry mints a fresh UUID,
    present returns its metadata.id untouched, unreadable returns "" (never re-credential). Writes nothing."""
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return str(uuid.uuid4())

    return load_registry(registry_path).get("metadata", {}).get("id", "") or ""


def save_registry(registry_path, data):
    """Save registry to JSON file. Auto-updates timestamp and sorts branches."""
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
    """Get next citizen number from registry (count of existing branches + 1)."""
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


def add_to_registry(registry_path, branch_name, branch_path, profile, email, purpose="", citizen_id="", credential=""):
    """Add a new branch entry to the registry.

    citizen_id: pass the id already in the passport; minting twice gives one citizen two ids.
    credential: written only into a registry being created here, never over an existing metadata.id.
    Returns True if added, False if already present or on error. Locked with fcntl on POSIX only."""
    registry_path = Path(registry_path)

    if not _validate_path_containment(branch_path, registry_path):
        logger.error("[registry] Path containment violation: %s escapes project root", branch_path)
        return False

    lock_path = registry_path.parent / f".{registry_path.stem}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if fcntl is None:
        lock_fd = None
    else:
        lock_fd = open(lock_path, "w", encoding="utf-8")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

    try:
        # Whether the file existed, not whether the dict has an id, decides who owns the credential.
        registry_existed = registry_path.exists()

        # Past this line the branch list is rebuilt from load_registry, which is empty for an unreadable file.
        if not registry_is_writable_document(registry_path):
            logger.error(
                "[registry] %s exists but could not be read as a registry document — refusing to add %s. "
                "Writing would replace every branch it holds with this one entry and drop metadata.id.",
                registry_path.name,
                branch_name,
            )
            return False

        registry = load_registry(registry_path)

        if credential and not registry_existed:
            registry.setdefault("metadata", {})["id"] = credential

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
        registry.setdefault("metadata", {})["total_branches"] = len(branches_as_list(branches))

        json_handler.log_operation("registry_updated", data={"branch": branch_name})

        return save_registry(registry_path, registry)
    finally:
        if lock_fd is not None and fcntl is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()


def fix_passport_registry_id(branch_dir: Path, registry_path: Path) -> bool | None:
    """Update passport.json registry_id if it doesn't match the current registry.

    True if updated, False if nothing to change, None if a read or write failed (never a success value)."""
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        return False
    if not registry_path.exists():
        return False

    try:
        registry_data = json_handler.read_json(registry_path)
        if registry_data is None:
            raise ValueError("the registry could not be read as JSON")
        current_id = registry_data.get("metadata", {}).get("id", "")
    except Exception as e:
        logger.warning("[registry] Cannot read registry_id from %s: %s", registry_path.name, e)
        return None

    if not current_id:
        return False

    try:
        passport = json_handler.read_json(passport_path)
        if passport is None:
            raise ValueError(f"passport at {passport_path} could not be read")
        old_id = passport.get("citizenship", {}).get("registry_id", "")
        if old_id == current_id:
            return False

        passport.setdefault("citizenship", {})["registry_id"] = current_id
        if not json_handler.write_json(passport_path, passport):
            raise OSError(f"passport at {passport_path} could not be written")
        logger.info(
            "[registry] Fixed registry_id for %s: %s → %s",
            branch_dir.name,
            old_id[:8] if old_id else "empty",
            current_id[:8],
        )
        return True
    except Exception as e:
        logger.warning("[registry] Failed to fix registry_id for %s: %s", branch_dir.name, e)
        return None


def pick_owner_branch(branches, project_root):
    """Select which branch entry should be the owner (no writes).

    A manager-class passport wins (cosmetic preference, not the gate), else the earliest created.
    Returns None when branches is empty."""
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

    return min(branches, key=lambda b: b.get("created", "9999-99-99"))


def ensure_project_has_owner(registry_path):
    """Ensure exactly one branch entry in the registry has owner:true (the entry, never the passport)."""
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

    branch_name exists so the refusal is testable; anything but ADMIN_BRANCH is refused by name.
    Returns (status, reason), status one of "granted", "already", "refused" (nothing written)."""
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
    if registry_path is None:
        reason = "REFUSED: no registry found — admin is granted in a registry, and there is none to grant it in"
        logger.warning("[registry] %s", reason)
        return "refused", reason

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

    Re-mints a missing or duplicated registry_id; an already-unique UUID is never touched."""
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
    """Return the branch entry dict whose owner==true, or None."""
    registry_path = find_registry(start_path=start_path)
    if registry_path is None or not registry_path.exists():
        return None
    reg_data = load_registry(registry_path)
    for branch in branches_as_list(reg_data.get("branches", [])):
        if branch.get("owner") is True:
            return branch
    return None


def is_owner(email, start_path=None):
    """True iff email matches the owner entry's email, with or without a leading '@'."""
    if not email:
        return False
    normalized = (email if email.startswith("@") else f"@{email}").lower()
    owner = get_owner(start_path=start_path)
    if owner is None:
        return False
    owner_email = owner.get("email", "")
    owner_normalized = (owner_email if owner_email.startswith("@") else f"@{owner_email}").lower()
    return normalized == owner_normalized
