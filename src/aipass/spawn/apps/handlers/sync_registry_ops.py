# =================== AIPass ====================
# Name: sync_registry_ops.py
# Description: Registry sync handler — implementation logic for registry repair
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Registry synchronization handler for branch lifecycle management.

Contains the core sync logic: scanning the filesystem, comparing with
*_REGISTRY.json, detecting stale/unregistered branches, and
optionally repairing mismatches.

CWD-aware: finds the local project registry from CWD (walks up parents
looking for *_REGISTRY.json) so it works for both AIPass and external projects.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    load_registry,
    save_registry,
    branches_as_list,
    fix_passport_registry_id,
    pick_owner_branch,
)
from aipass.spawn.apps.handlers.meta_ops import (
    load_template_registry,
    generate_branch_meta,
    save_branch_meta,
)
from aipass.spawn.apps.handlers.file_ops import regenerate_template_registry
from aipass.spawn.apps.handlers.class_registry import get_template_dir, refuse_forbidden_class
from aipass.spawn.apps.handlers.json import json_handler


def resolve_sync_template_class(citizen_class: str, branch_name: str) -> Path:
    """Resolve a passport's citizen_class to a template dir for a sync rebuild.

    A merely-unknown class still falls back to aipass_framework (sync repairs
    drifted branches; a stale class name shouldn't block the repair). A
    FORBIDDEN class does not: "admin" is a devpulse-only registry privilege,
    so sync refuses to scaffold anything claiming it (DPLAN-0288).

    Args:
        citizen_class: The value read from the branch's passport.
        branch_name: Branch name, for the refusal message.

    Returns:
        Path to the template directory to rebuild against.

    Raises:
        ValueError: The class is forbidden — caller must skip this branch.
    """
    refusal = refuse_forbidden_class(citizen_class)
    if refusal:
        raise ValueError(f"{branch_name}: {refusal}")

    try:
        return get_template_dir(citizen_class)
    except ValueError:
        logger.warning(
            f"[sync-registry] Unknown class '{citizen_class}' for {branch_name}, falling back to aipass_framework"
        )
        return get_template_dir("aipass_framework")


def _derive_description(branch_path: Path) -> str:
    """Derive a one-line description from the branch's passport or README."""
    passport_path = branch_path / ".trinity" / "passport.json"
    if passport_path.exists():
        try:
            passport = json.loads(passport_path.read_text(encoding="utf-8"))
            identity = passport.get("identity", {})
            for field in ("purpose", "role"):
                value = identity.get(field, "").strip()
                if value:
                    return value
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[sync-registry] Failed to read passport for description (%s): %s", branch_path.name, e)

    readme_path = branch_path / "README.md"
    if readme_path.exists():
        try:
            for line in readme_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith(("#", "[", "---", "*", ">")):
                    return stripped
        except IOError as e:
            logger.warning("[sync-registry] Failed to read README for description (%s): %s", branch_path.name, e)

    return "Auto-registered branch"


def _scan_for_branches(project_root: Path) -> dict[str, Path]:
    """Scan a project directory tree for branches with .trinity/passport.json.

    Searches both the root level and common subdirectories (src/, src/*/):
    - project_root/*/.trinity/passport.json  (root-level agents)
    - project_root/src/*/.trinity/passport.json  (src/ agents)
    - project_root/src/*/*/.trinity/passport.json  (nested src, e.g. src/aipass/*)

    Args:
        project_root: The project root directory (registry parent).

    Returns:
        Dict mapping lowercase branch name to its directory Path.
    """
    found: dict[str, Path] = {}

    def _check_dir(directory: Path) -> None:
        if not directory.is_dir():
            return
        for child in sorted(directory.iterdir()):
            if child.is_dir() and not child.name.startswith(".") and not child.name.startswith("__"):
                passport = child / ".trinity" / "passport.json"
                if passport.exists():
                    found[child.name.lower()] = child

    # Level 1: project_root/*/
    _check_dir(project_root)

    # Level 2: project_root/src/*/
    src_dir = project_root / "src"
    if src_dir.is_dir():
        _check_dir(src_dir)
        # Level 3: project_root/src/*/*/  (e.g. src/aipass/*)
        for sub in sorted(src_dir.iterdir()):
            if sub.is_dir() and not sub.name.startswith(".") and not sub.name.startswith("__"):
                _check_dir(sub)

    return found


# =============================================================================
# PUBLIC API
# =============================================================================


def sync_registry(fix: bool = False) -> dict:
    """Synchronize *_REGISTRY.json with filesystem.

    CWD-aware: uses find_registry() which walks up from CWD to find the
    project's registry. Works for both AIPass and external projects.

    Workflow:
    1. Find and load *_REGISTRY.json (CWD-aware)
    2. Scan project directories for .trinity/passport.json (branch marker)
    3. Compare:
       - Stale entries: registered in JSON but directory missing or no passport
       - Unregistered: directory exists with passport but not in JSON
    4. Report findings
    5. If fix=True:
       - Remove stale entries
       - Add unregistered branches with basic metadata
       - Save updated registry

    Returns:
        Dict with sync results.
    """
    # 1. Load registry — CWD-aware discovery
    registry_path = find_registry()
    project_root = registry_path.parent
    registry = load_registry(registry_path)
    branches = branches_as_list(registry.get("branches", []))

    # Build lookup of registered branch names (lowercase) -> entry
    registered: dict[str, dict] = {}
    for entry in branches:
        name = entry.get("name", "").lower()
        if name:
            registered[name] = entry

    # 2. Scan filesystem for branch directories with .trinity/passport.json
    filesystem_branches = _scan_for_branches(project_root)

    # 3. Compare
    stale: list[str] = []
    unregistered_list: list[str] = []
    healthy: list[str] = []

    # Check registered branches against filesystem
    resolved_root = project_root.resolve()
    for name, entry in registered.items():
        rel_path = entry.get("path", "")
        branch_dir = (project_root / rel_path).resolve() if rel_path else None

        if branch_dir and branch_dir.is_dir():
            try:
                branch_dir.relative_to(resolved_root)
            except ValueError:
                stale.append(name)
                logger.info("[sync-registry] Entry '%s' path escapes project root: %s", name, rel_path)
                continue

            passport = branch_dir / ".trinity" / "passport.json"
            if passport.exists():
                healthy.append(name)
            else:
                # Directory exists but no passport — treat as stale
                stale.append(name)
        else:
            stale.append(name)

    # Check filesystem branches against registry
    for name, _path in filesystem_branches.items():
        if name not in registered:
            unregistered_list.append(name)

    logger.info(
        f"[sync-registry] Scan complete: "
        f"healthy={len(healthy)}, stale={len(stale)}, unregistered={len(unregistered_list)}"
    )

    # 4/5. Fix if requested
    fixed = False
    needs_save = False
    if fix and (stale or unregistered_list):
        # Remove stale entries
        raw_branches = registry.get("branches", [])
        if stale:
            if isinstance(raw_branches, dict):
                for key in list(raw_branches.keys()):
                    entry_name = (
                        raw_branches[key].get("name", "").lower()
                        if isinstance(raw_branches[key], dict)
                        else key.lower()
                    )
                    if entry_name in stale or key.lower() in stale:
                        del raw_branches[key]
            else:
                raw_branches = [b for b in raw_branches if b.get("name", "").lower() not in stale]
            registry["branches"] = raw_branches
            for s in stale:
                logger.info(f"[sync-registry] Removed stale entry: {s}")

        # Add unregistered branches
        today = datetime.now().strftime("%Y-%m-%d")
        for name in unregistered_list:
            branch_path = filesystem_branches[name]
            rel_path = branch_path.relative_to(project_root).as_posix()

            entry = {
                "name": name.upper(),
                "path": rel_path,
                "profile": "library",
                "description": _derive_description(branch_path),
                "email": f"@{name}",
                "status": "active",
                "created": today,
                "last_active": today,
            }
            raw_branches = registry["branches"]
            if isinstance(raw_branches, dict):
                raw_branches[name.upper()] = entry
            else:
                raw_branches.append(entry)
            logger.info(f"[sync-registry] Added unregistered branch: {name}")

        registry["metadata"]["total_branches"] = len(branches_as_list(registry["branches"]))
        needs_save = True

    # Backfill placeholder descriptions on existing entries
    descriptions_backfilled = []
    if fix:
        for entry in branches_as_list(registry.get("branches", [])):
            if entry.get("description") == "Auto-registered branch":
                name_lower = entry.get("name", "").lower()
                branch_path = filesystem_branches.get(name_lower)
                if branch_path:
                    derived = _derive_description(branch_path)
                    if derived != "Auto-registered branch":
                        entry["description"] = derived
                        descriptions_backfilled.append(name_lower)
                        logger.info("[sync-registry] Backfilled description for %s: %s", name_lower, derived)
        if descriptions_backfilled:
            needs_save = True

    if fix and needs_save:
        save_result = save_registry(registry_path, registry)
        fixed = save_result
        if fixed:
            logger.info("[sync-registry] Registry updated successfully")
        else:
            logger.error("[sync-registry] Failed to save updated registry")

    # Rebuild .spawn/ tracking for branches missing metadata
    spawn_rebuilt = []
    if fix:
        for name in healthy + unregistered_list:
            branch_path = filesystem_branches.get(name)
            if not branch_path:
                continue

            # Check/rebuild .spawn/.template_registry.json
            spawn_dir = branch_path / ".spawn"
            spawn_dir.mkdir(exist_ok=True)
            template_reg_path = spawn_dir / ".template_registry.json"
            if not template_reg_path.exists():
                regenerate_template_registry(branch_path)

            # Check/rebuild .spawn/.branch_meta.json
            branch_meta_path = spawn_dir / ".branch_meta.json"
            if not branch_meta_path.exists():
                # Determine citizen class from passport
                passport_path = branch_path / ".trinity" / "passport.json"
                citizen_class = "aipass_framework"  # default
                if passport_path.exists():
                    try:
                        passport = json.loads(passport_path.read_text(encoding="utf-8"))
                        citizen_class = passport.get("identity", {}).get("citizen_class", "aipass_framework")
                    except (json.JSONDecodeError, IOError) as e:
                        logger.warning(f"Failed to read passport for citizen class detection ({name}): {e}")

                # Resolve the template for that class — forbidden classes refuse
                # loudly and skip the branch rather than being scaffolded.
                try:
                    template_dir = resolve_sync_template_class(citizen_class, name)
                except ValueError as e:
                    logger.error(f"[sync-registry] {e}")
                    continue
                template_registry = load_template_registry(template_dir)
                if template_registry:
                    branch_meta = generate_branch_meta(branch_path, template_registry)
                    save_branch_meta(branch_path, branch_meta)
                    spawn_rebuilt.append(name)
                    logger.info(f"[sync-registry] Rebuilt .spawn/ for: {name}")

    # Fix registry_id mismatches in passports for all known branches
    ids_fixed = []
    if fix:
        all_known = list(healthy) + list(unregistered_list)
        for name in all_known:
            branch_path = filesystem_branches.get(name)
            if branch_path:
                was_fixed = fix_passport_registry_id(branch_path, registry_path)
                if was_fixed:
                    ids_fixed.append(name)

    json_handler.log_operation("registry_scanned")

    return {
        "stale": stale,
        "unregistered": unregistered_list,
        "healthy": healthy,
        "fixed": fixed,
        "spawn_rebuilt": spawn_rebuilt,
        "ids_fixed": ids_fixed,
        "descriptions_backfilled": descriptions_backfilled,
    }


# =============================================================================
# OWNER / IDENTITY CHECK + FIX  (DPLAN-0239 P4, frozen contract)
# =============================================================================


def check_owner_identity(registry_path=None):
    """Read-only owner/identity health check — 7 flags.

    Flags:
      no_owner            — no branch entry has owner:true
      multi_owner         — more than one branch has owner:true
      owner_missing_branch — owner entry's path doesn't exist on disk
      owner_wrong_branch  — owner is not the manager and not the first agent
      metadata_id_missing — registry metadata.id absent
      passport_mismatch   — passport citizenship.registry_id != metadata.id
      entry_rid_stale     — entry registry_id missing, duplicate, or == metadata.id

    Returns:
        dict with pinned schema:
          ``clean`` (bool), ``owner`` (name str or None),
          ``owner_uid`` (entry registry_id str, empty if none),
          ``issues`` (list of flag/detail/branch dicts).
    """
    if registry_path is None:
        registry_path = find_registry()
    registry_path = Path(registry_path)
    reg_data = load_registry(registry_path)
    branches = branches_as_list(reg_data.get("branches", []))
    project_root = registry_path.parent
    metadata_id = reg_data.get("metadata", {}).get("id", "")

    issues: list[dict] = []

    # --- flag 1: no_owner ---
    owners = [b for b in branches if b.get("owner") is True]
    if not owners:
        issues.append({"flag": "no_owner", "detail": "No branch entry has owner:true"})

    # --- flag 2: multi_owner ---
    if len(owners) > 1:
        names = [b.get("name", "?") for b in owners]
        issues.append({"flag": "multi_owner", "detail": f"Multiple owners: {', '.join(names)}"})

    # --- flag 3: owner_missing_branch ---
    for owner in owners:
        owner_path = (project_root / owner.get("path", "")).resolve()
        if not owner_path.is_dir():
            issues.append(
                {
                    "flag": "owner_missing_branch",
                    "detail": f"Owner {owner.get('name', '?')} path does not exist: {owner.get('path', '')}",
                }
            )

    # --- flag 4: owner_wrong_branch ---
    for owner in owners:
        owner_dir = project_root / owner.get("path", "")
        passport_path = owner_dir / ".trinity" / "passport.json"
        is_manager = False
        if passport_path.exists():
            try:
                passport = json.loads(passport_path.read_text(encoding="utf-8"))
                is_manager = passport.get("identity", {}).get("citizen_class") == "manager"
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("[check-identity] Cannot read passport for %s: %s", owner.get("name", "?"), e)
        if not is_manager and branches:
            first = min(branches, key=lambda b: b.get("created", "9999-99-99"))
            if owner.get("name") != first.get("name"):
                issues.append(
                    {
                        "flag": "owner_wrong_branch",
                        "detail": f"Owner {owner.get('name', '?')} is not the manager and not the first agent",
                    }
                )

    # --- flag 5: metadata_id_missing ---
    if not metadata_id:
        issues.append({"flag": "metadata_id_missing", "detail": "Registry metadata.id is absent"})

    # --- flag 6: passport_mismatch ---
    if metadata_id:
        for branch in branches:
            branch_dir = project_root / branch.get("path", "")
            passport_path = branch_dir / ".trinity" / "passport.json"
            if not passport_path.exists():
                continue
            try:
                passport = json.loads(passport_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("[check-identity] Cannot read passport for %s: %s", branch.get("name", "?"), e)
                continue
            passport_rid = passport.get("citizenship", {}).get("registry_id", "")
            if passport_rid and passport_rid != metadata_id:
                issues.append(
                    {
                        "flag": "passport_mismatch",
                        "detail": (
                            f"{branch.get('name', '?')}: passport registry_id="
                            f"{passport_rid[:8]}… != metadata.id={metadata_id[:8]}…"
                        ),
                        "branch": branch.get("name", ""),
                    }
                )

    # --- flag 7: entry_rid_stale ---
    rid_counts: dict[str, int] = {}
    for branch in branches:
        rid = branch.get("registry_id", "")
        if rid:
            rid_counts[rid] = rid_counts.get(rid, 0) + 1

    for branch in branches:
        rid = branch.get("registry_id", "")
        if not rid:
            issues.append(
                {
                    "flag": "entry_rid_stale",
                    "detail": f"{branch.get('name', '?')}: entry registry_id missing",
                    "branch": branch.get("name", ""),
                }
            )
        elif metadata_id and rid == metadata_id:
            issues.append(
                {
                    "flag": "entry_rid_stale",
                    "detail": f"{branch.get('name', '?')}: entry registry_id is a stale copy of metadata.id",
                    "branch": branch.get("name", ""),
                }
            )
        elif rid_counts.get(rid, 0) > 1:
            issues.append(
                {
                    "flag": "entry_rid_stale",
                    "detail": f"{branch.get('name', '?')}: entry registry_id={rid[:8]}… is a duplicate",
                    "branch": branch.get("name", ""),
                }
            )

    owner_entry = owners[0] if len(owners) == 1 else None
    return {
        "clean": len(issues) == 0,
        "owner": owner_entry.get("name") if owner_entry else None,
        "owner_uid": owner_entry.get("registry_id", "") if owner_entry else "",
        "issues": issues,
    }


def fix_owner_identity(registry_path=None, dry_run=False):
    """Reconcile owner + identity in the sealed registry.

    Actions (each idempotent, refuses to alter correct state):
      - Seat missing owner (first agent)
      - Restore missing metadata.id (consensus from passports, else mint)
      - Align passports to metadata.id
      - Mint per-citizen entry registry_id where missing or stale-duplicate
      - Resolve multi-owner (keep first-created, unseat others)

    Deliberately NEVER moves a seated owner — ``owner_wrong_branch`` is a
    flag-only diagnostic for human decision.

    Args:
        registry_path: Path to registry (None = auto-discover from CWD).
        dry_run: If True, print planned changes but don't write.

    Returns:
        dict with ``actions`` (list of change descriptions) and ``applied`` (bool).
    """
    if registry_path is None:
        registry_path = find_registry()
    registry_path = Path(registry_path)
    reg_data = load_registry(registry_path)
    branches = branches_as_list(reg_data.get("branches", []))
    project_root = registry_path.parent
    metadata_id = reg_data.get("metadata", {}).get("id", "")

    actions: list[str] = []
    registry_changed = False

    # --- restore missing metadata.id (majority-restore or mint) ---
    if not metadata_id:
        passport_id_counts: dict[str, int] = {}
        for branch in branches:
            branch_dir = project_root / branch.get("path", "")
            passport_path = branch_dir / ".trinity" / "passport.json"
            if not passport_path.exists():
                continue
            try:
                passport = json.loads(passport_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("[fix-identity] Cannot read passport for consensus: %s", e)
                continue
            rid = passport.get("citizenship", {}).get("registry_id", "")
            if rid:
                passport_id_counts[rid] = passport_id_counts.get(rid, 0) + 1

        total_with_id = sum(passport_id_counts.values())
        majority_id = None
        if passport_id_counts:
            top_id = max(passport_id_counts, key=lambda k: passport_id_counts[k])
            if passport_id_counts[top_id] > total_with_id / 2:
                majority_id = top_id

        if majority_id:
            metadata_id = majority_id
            count = passport_id_counts[majority_id]
            actions.append(f"Restore metadata.id = {metadata_id[:8]}… (passport majority {count} of {total_with_id})")
        else:
            metadata_id = str(uuid.uuid4())
            actions.append(f"Mint metadata.id = {metadata_id[:8]}…")

        reg_data.setdefault("metadata", {})["id"] = metadata_id
        registry_changed = True

    # --- resolve multi-owner: keep earliest-created, unseat the rest ---
    owners = [b for b in branches if b.get("owner") is True]
    if len(owners) > 1:
        owners_sorted = sorted(owners, key=lambda b: b.get("created", "9999-99-99"))
        for extra in owners_sorted[1:]:
            extra.pop("owner", None)
            actions.append(f"Unseat extra owner: {extra.get('name', '?')}")
            registry_changed = True

    # --- seat missing owner (canonical heuristic) ---
    current_owners = [b for b in branches if b.get("owner") is True]
    if not current_owners and branches:
        chosen = pick_owner_branch(branches, project_root)
        if chosen:
            chosen["owner"] = True
            actions.append(f"Seat owner: {chosen.get('name', '?')}")
            registry_changed = True

    # --- mint per-citizen entry registry_id where missing or stale ---
    rid_counts: dict[str, int] = {}
    for branch in branches:
        rid = branch.get("registry_id", "")
        if rid:
            rid_counts[rid] = rid_counts.get(rid, 0) + 1

    for branch in branches:
        rid = branch.get("registry_id", "")
        needs_mint = False
        if not rid:
            needs_mint = True
        elif metadata_id and rid == metadata_id:
            needs_mint = True
        elif rid_counts.get(rid, 0) > 1:
            needs_mint = True

        if needs_mint:
            new_rid = str(uuid.uuid4())
            old_display = rid[:8] + "…" if rid else "(empty)"
            branch["registry_id"] = new_rid
            actions.append(f"Mint citizen UID for {branch.get('name', '?')}: {old_display} → {new_rid[:8]}…")
            registry_changed = True

    # --- align passports to metadata.id ---
    passport_actions: list[str] = []
    for branch in branches:
        branch_dir = project_root / branch.get("path", "")
        passport_path = branch_dir / ".trinity" / "passport.json"
        if not passport_path.exists():
            continue
        try:
            passport = json.loads(passport_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[fix-identity] Cannot read passport for %s: %s", branch.get("name", "?"), e)
            continue
        passport_rid = passport.get("citizenship", {}).get("registry_id", "")
        if passport_rid != metadata_id:
            old_display = passport_rid[:8] + "…" if passport_rid else "(empty)"
            passport.setdefault("citizenship", {})["registry_id"] = metadata_id
            if not dry_run:
                try:
                    passport_path.write_text(json.dumps(passport, indent=2, ensure_ascii=False), encoding="utf-8")
                except IOError as e:
                    logger.warning("[fix-identity] Failed to write passport %s: %s", branch.get("name", "?"), e)
                    continue
            passport_actions.append(f"Align passport for {branch.get('name', '?')}: {old_display} → {metadata_id[:8]}…")

    actions.extend(passport_actions)

    # --- migrate legacy citizen_class "builder" → "aipass_framework" ---
    for branch in branches:
        branch_dir = project_root / branch.get("path", "")
        passport_path = branch_dir / ".trinity" / "passport.json"
        if not passport_path.exists():
            continue
        try:
            passport = json.loads(passport_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("[fix-identity] Cannot read passport for migration: %s", e)
            continue
        current_class = passport.get("identity", {}).get("citizen_class", "")
        if current_class != "builder":
            continue
        passport.setdefault("identity", {})["citizen_class"] = "aipass_framework"
        if not dry_run:
            try:
                passport_path.write_text(json.dumps(passport, indent=2, ensure_ascii=False), encoding="utf-8")
            except IOError as e:
                logger.warning("[fix-identity] Failed to migrate citizen_class for %s: %s", branch.get("name", "?"), e)
                continue
        actions.append(f"Migrate citizen_class for {branch.get('name', '?')}: builder → aipass_framework")

    applied = False
    if registry_changed and not dry_run:
        applied = save_registry(registry_path, reg_data)
        if applied:
            logger.info("[fix-identity] Registry updated with %d action(s)", len(actions))
        else:
            logger.error("[fix-identity] Failed to save registry")

    if not registry_changed and actions and not dry_run:
        applied = True

    if dry_run and actions:
        logger.info("[fix-identity] Dry-run: %d action(s) planned", len(actions))

    return {"actions": actions, "applied": applied}
