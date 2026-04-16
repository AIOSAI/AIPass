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
from datetime import datetime
from pathlib import Path

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.registry import (
    find_registry,
    load_registry,
    save_registry,
    _branches_as_list,
    fix_passport_registry_id,
)
from aipass.spawn.apps.handlers.meta_ops import (
    load_template_registry,
    generate_branch_meta,
    save_branch_meta,
)
from aipass.spawn.apps.handlers.file_ops import regenerate_template_registry
from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.handlers.json import json_handler


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
    branches = _branches_as_list(registry.get("branches", []))

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
    for name, entry in registered.items():
        rel_path = entry.get("path", "")
        branch_dir = (project_root / rel_path).resolve() if rel_path else None

        if branch_dir and branch_dir.is_dir():
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
            rel_path = str(branch_path.relative_to(project_root))

            entry = {
                "name": name.upper(),
                "path": rel_path,
                "profile": "library",
                "description": "Auto-registered branch",
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

        # Update total and save
        registry["metadata"]["total_branches"] = len(_branches_as_list(registry["branches"]))
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
                citizen_class = "builder"  # default
                if passport_path.exists():
                    try:
                        passport = json.loads(passport_path.read_text(encoding="utf-8"))
                        citizen_class = passport.get("identity", {}).get("citizen_class", "builder")
                    except (json.JSONDecodeError, IOError) as e:
                        logger.warning(f"Failed to read passport for citizen class detection ({name}): {e}")

                # Load template registry for that class (fall back to builder if unknown)
                try:
                    template_dir = get_template_dir(citizen_class)
                except ValueError:
                    logger.warning(
                        f"[sync-registry] Unknown class '{citizen_class}' for {name}, falling back to builder"
                    )
                    template_dir = get_template_dir("builder")
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
    }
