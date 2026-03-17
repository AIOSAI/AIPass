# =================== AIPass ====================
# Name: update_ops.py
# Description: Update handler — implementation logic for branch updates
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-03-10
# =============================================

"""Update handler implementation for branch lifecycle management.

Contains the core update logic: resolving branch paths, executing renames,
additions, JSON updates, pruned file archival, and coordinating the full
update workflow for single and all-branch modes.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from aipass.prax.apps.modules.logger import system_logger as logger

from aipass.spawn.apps.handlers.meta_ops import (
    generate_branch_meta,
    get_template_dir,
    load_branch_meta,
    load_template_registry,
    save_branch_meta,
)
from aipass.spawn.apps.handlers.reconcile import reconcile_branch_state
from aipass.spawn.apps.handlers.change_detection import detect_changes
from aipass.spawn.apps.handlers.json_ops import backup_json, deep_merge
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, replace_placeholders
from aipass.spawn.apps.handlers.registry import find_registry, load_registry, _branches_as_list
from aipass.spawn.apps.handlers.json import json_handler

# Repo root — resolved from spawn package location
_REPO_ROOT = Path(__file__).parents[5]  # handlers/apps/spawn/aipass/src/AIPass


# =============================================================================
# PUBLIC API
# =============================================================================

def update_branch(branch_name: str, dry_run: bool = False, trace: bool = False) -> dict:
    """Update a single branch from template.

    Workflow:
    1. Resolve branch path from AIPASS_REGISTRY.json
    2. Load template registry
    3. Load or generate .spawn/.branch_meta.json
    4. Pre-flight reconciliation
    5. Change detection
    6. If dry_run -> print summary, return
    7. Execute changes (renames, additions, JSON updates, pruned archival)
    8. Update branch metadata with new tracking state
    9. Post-flight reconciliation
    10. Return summary dict

    Returns:
        Dict with update results including counts and errors.
    """
    errors: list[str] = []
    counts = {
        "additions": 0,
        "renames": 0,
        "updates": 0,
        "pruned": 0,
        "skipped_py": 0,
    }

    # ------------------------------------------------------------------
    # 1. Resolve branch path
    # ------------------------------------------------------------------
    branch_dir = _resolve_branch_path(branch_name)
    if branch_dir is None:
        return _result(branch_name, False, counts, [f"Branch '{branch_name}' not found in registry"], dry_run)

    if not branch_dir.is_dir():
        return _result(branch_name, False, counts, [f"Branch directory does not exist: {branch_dir}"], dry_run)

    if trace:
        logger.info(f"[update] Resolved {branch_name} -> {branch_dir}")

    # ------------------------------------------------------------------
    # 1b. Read citizen_class from passport
    # ------------------------------------------------------------------
    citizen_class = _read_citizen_class(branch_dir)
    if trace:
        logger.info(f"[update] Citizen class: {citizen_class}")

    # ------------------------------------------------------------------
    # 2. Load template registry
    # ------------------------------------------------------------------
    template_dir = get_template_dir(citizen_class)
    template_registry = load_template_registry(template_dir)
    if template_registry is None:
        return _result(branch_name, False, counts, ["Failed to load template registry"], dry_run)

    if trace:
        t_files = len(template_registry.get("files", {}))
        t_dirs = len(template_registry.get("directories", {}))
        logger.info(f"[update] Template registry: {t_files} files, {t_dirs} dirs")

    # ------------------------------------------------------------------
    # 3. Load or generate branch metadata (first-time adoption)
    # ------------------------------------------------------------------
    branch_meta = load_branch_meta(branch_dir)
    first_time = branch_meta is None

    if first_time:
        if trace:
            logger.info(f"[update] No branch_meta found — generating initial metadata (adoption)")
        branch_meta = generate_branch_meta(branch_dir, template_registry)
        if not dry_run:
            save_branch_meta(branch_dir, branch_meta)
            if trace:
                logger.info("[update] Saved initial branch_meta.json")

    # ------------------------------------------------------------------
    # 4. Pre-flight reconciliation
    # ------------------------------------------------------------------
    recon = reconcile_branch_state(branch_dir, branch_meta, trace=trace)
    if trace:
        logger.info(
            f"[update] Pre-flight: missing={len(recon['missing_files'])}, "
            f"untracked={len(recon['untracked_files'])}, "
            f"hash_mismatches={len(recon['hash_mismatches'])}, "
            f"missing_dirs={len(recon['missing_dirs'])}"
        )

    # ------------------------------------------------------------------
    # 5. Change detection
    # ------------------------------------------------------------------
    changes = detect_changes(template_registry, branch_meta, branch_dir)

    additions = changes.get("additions", [])
    updates_list = changes.get("updates", [])
    renames = changes.get("renames", [])
    pruned = changes.get("pruned", [])

    if trace:
        logger.info(
            f"[update] Changes detected: additions={len(additions)}, "
            f"updates={len(updates_list)}, renames={len(renames)}, "
            f"pruned={len(pruned)}"
        )

    # ------------------------------------------------------------------
    # 6. Dry run — just report
    # ------------------------------------------------------------------
    if dry_run:
        counts["additions"] = len(additions)
        counts["renames"] = len(renames)
        counts["pruned"] = len(pruned)

        # Count updates vs skipped .py files
        for upd in updates_list:
            tp = upd.get("template_path", "")
            if tp.endswith(".py"):
                counts["skipped_py"] += 1
            elif tp.endswith(".json"):
                counts["updates"] += 1

        return _result(branch_name, True, counts, errors, dry_run,
                       _additions_detail=additions, _updates_detail=updates_list,
                       _renames_detail=renames, _pruned_detail=pruned)

    # ------------------------------------------------------------------
    # 7. Execute changes
    # ------------------------------------------------------------------

    # Build placeholder replacements for this branch
    replacements = build_replacements_dict(branch_dir, branch_name)

    # 7a. RENAMES
    for rename_info in renames:
        try:
            _execute_rename(branch_dir, rename_info, trace)
            counts["renames"] += 1
        except Exception as exc:
            msg = f"Rename failed for {rename_info.get('file_id')}: {exc}"
            errors.append(msg)
            logger.error(f"[update] {msg}")

    # 7b. ADDITIONS
    for add_info in additions:
        try:
            _execute_addition(branch_dir, template_dir, add_info, replacements, template_registry, trace)
            counts["additions"] += 1
        except Exception as exc:
            msg = f"Addition failed for {add_info.get('file_id')}: {exc}"
            errors.append(msg)
            logger.error(f"[update] {msg}")

    # 7c. JSON UPDATES (skip .py files, deep merge .json)
    for upd_info in updates_list:
        try:
            result = _execute_update(branch_dir, template_dir, upd_info, replacements, trace)
            if result == "updated":
                counts["updates"] += 1
            elif result == "skipped_py":
                counts["skipped_py"] += 1
        except Exception as exc:
            msg = f"Update failed for {upd_info.get('file_id')}: {exc}"
            errors.append(msg)
            logger.error(f"[update] {msg}")

    # 7d. PRUNED — archive, don't delete
    for prune_info in pruned:
        try:
            _execute_prune(branch_dir, prune_info, trace)
            counts["pruned"] += 1
        except Exception as exc:
            msg = f"Prune/archive failed for {prune_info.get('file_id')}: {exc}"
            errors.append(msg)
            logger.error(f"[update] {msg}")

    # ------------------------------------------------------------------
    # 8. Refresh branch metadata
    # ------------------------------------------------------------------
    updated_meta = generate_branch_meta(branch_dir, template_registry)
    updated_meta["metadata"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    save_branch_meta(branch_dir, updated_meta)

    if trace:
        logger.info("[update] Branch metadata refreshed and saved")

    # ------------------------------------------------------------------
    # 9. Post-flight reconciliation
    # ------------------------------------------------------------------
    post_recon = reconcile_branch_state(branch_dir, updated_meta, trace=trace)
    if trace:
        logger.info(
            f"[update] Post-flight: missing={len(post_recon['missing_files'])}, "
            f"untracked={len(post_recon['untracked_files'])}"
        )

    # ------------------------------------------------------------------
    # 10. Return summary
    # ------------------------------------------------------------------
    success = len(errors) == 0
    if success:
        json_handler.log_operation("update_executed", data={"branch": branch_name})
    return _result(branch_name, success, counts, errors, dry_run)


def update_all(dry_run: bool = False, trace: bool = False, citizen_class: str | None = None) -> list[dict]:
    """Update all branches from AIPASS_REGISTRY.json.

    Iterates through all registered branches, calls update_branch() for each.
    Skips spawn itself (can't update yourself).
    When citizen_class is specified, only updates branches of that class.
    Returns list of result dicts.
    """
    registry_path = find_registry()
    registry = load_registry(registry_path)
    branches = _branches_as_list(registry.get("branches", []))

    if not branches:
        return []

    results: list[dict] = []

    for branch_entry in branches:
        name = branch_entry.get("name", "")
        lower_name = name.lower()

        # Skip spawn itself
        if lower_name == "spawn":
            if trace:
                logger.info("[update] Skipping spawn (self)")
            continue

        # Check class filter if specified
        if citizen_class:
            branch_dir = _resolve_branch_path(lower_name)
            if branch_dir and branch_dir.is_dir():
                actual_class = _read_citizen_class(branch_dir)
                if actual_class != citizen_class:
                    if trace:
                        logger.info(f"[update] Skipping {name} (class={actual_class}, filter={citizen_class})")
                    continue

        if trace:
            logger.info(f"[update] Processing branch: {name}")

        try:
            result = update_branch(lower_name, dry_run=dry_run, trace=trace)
            results.append(result)
        except Exception as exc:
            logger.error(f"[update] Error updating {name}: {exc}")
            results.append({
                "branch": lower_name,
                "success": False,
                "additions": 0,
                "renames": 0,
                "updates": 0,
                "pruned": 0,
                "skipped_py": 0,
                "errors": [str(exc)],
                "dry_run": dry_run,
            })

    return results


# =============================================================================
# INTERNAL EXECUTION FUNCTIONS
# =============================================================================

def _read_citizen_class(branch_dir: Path) -> str:
    """Read citizen_class from a branch's passport.json.

    Falls back to "builder" if passport doesn't exist or doesn't have
    the citizen_class field (backward compatibility for pre-class branches).
    """
    passport_path = branch_dir / ".trinity" / "passport.json"
    if not passport_path.exists():
        return "builder"
    try:
        data = json.loads(passport_path.read_text(encoding="utf-8"))
        return data.get("identity", {}).get("citizen_class", "builder")
    except (json.JSONDecodeError, IOError):
        return "builder"


def _resolve_branch_path(branch_name: str) -> Path | None:
    """Resolve a branch name to its absolute directory path via the registry.

    Tries both the exact name and common case variants.
    Registry paths are relative to repo root.
    """
    registry_path = find_registry()
    registry = load_registry(registry_path)

    for branch in _branches_as_list(registry.get("branches", [])):
        reg_name = branch.get("name", "")
        if reg_name.lower() == branch_name.lower():
            rel_path = branch.get("path", "")
            if rel_path:
                return (_REPO_ROOT / rel_path).resolve()

    return None


def _execute_rename(branch_dir: Path, rename_info: dict, trace: bool) -> None:
    """Rename a file within the branch to match template's new path."""
    old_path = branch_dir / rename_info.get("branch_path", "")
    new_rel = rename_info.get("new_name", "")  # This is the new template-relative path
    new_path = branch_dir / new_rel

    if not old_path.exists():
        if trace:
            logger.info(f"[update] Rename: source not found, skipping: {old_path}")
        return

    # Create parent dirs if needed
    new_path.parent.mkdir(parents=True, exist_ok=True)

    old_path.rename(new_path)
    if trace:
        logger.info(f"[update] Renamed: {rename_info.get('branch_path')} -> {new_rel}")


def _execute_addition(
    branch_dir: Path,
    template_dir: Path,
    add_info: dict,
    replacements: dict,
    _template_registry: dict,
    trace: bool,
) -> None:
    """Copy a new template file/directory to the branch with placeholder replacement."""
    template_path = add_info.get("template_path", "")
    file_id = add_info.get("file_id", "")

    if not template_path:
        return

    # Check if this is a directory addition (ID starts with 'd')
    if file_id.startswith("d"):
        dest = branch_dir / template_path
        # Apply placeholder replacement to path
        dest_str = replace_placeholders(str(dest), replacements)
        dest = Path(dest_str)
        dest.mkdir(parents=True, exist_ok=True)
        if trace:
            logger.info(f"[update] Added directory: {template_path}")
        return

    # File addition — read from template, apply placeholders, write to branch
    source = template_dir / template_path
    dest = branch_dir / template_path

    # Apply placeholder replacement to destination path components
    dest_rel_str = replace_placeholders(template_path, replacements)
    dest = branch_dir / dest_rel_str

    if not source.exists():
        if trace:
            logger.info(f"[update] Template source not found, skipping: {source}")
        return

    # NEVER overwrite existing .py files — even during additions
    if dest.exists() and dest.suffix == ".py":
        if trace:
            logger.info(f"[update] SKIPPED existing .py file: {dest_rel_str}")
        return

    # Create parent directories
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Don't overwrite any existing file — additions are for MISSING files only
    if dest.exists():
        if trace:
            logger.info(f"[update] SKIPPED existing file: {dest_rel_str}")
        return

    try:
        content = source.read_text(encoding="utf-8")
        content = replace_placeholders(content, replacements)
        dest.write_text(content, encoding="utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        # Binary file — copy directly
        shutil.copy2(source, dest)

    if trace:
        logger.info(f"[update] Added: {dest_rel_str}")


def _execute_update(
    branch_dir: Path,
    template_dir: Path,
    upd_info: dict,
    replacements: dict,
    trace: bool,
) -> str:
    """Handle a file update from template.

    Returns:
        "updated" if file was merged, "skipped_py" if .py file, "skipped" otherwise.
    """
    template_path = upd_info.get("template_path", "")
    branch_path = upd_info.get("branch_path", "")

    if not template_path or not branch_path:
        return "skipped"

    # NEVER overwrite .py files
    if template_path.endswith(".py") or branch_path.endswith(".py"):
        if trace:
            logger.info(f"[update] SKIPPED .py file (manual review needed): {branch_path}")
        return "skipped_py"

    # JSON files — deep merge
    if template_path.endswith(".json") and branch_path.endswith(".json"):
        source = template_dir / template_path
        dest = branch_dir / branch_path

        if not source.exists() or not dest.exists():
            if trace:
                logger.info(f"[update] Source or dest missing for JSON merge: {template_path}")
            return "skipped"

        try:
            # Backup existing file first
            backup_json(dest)

            # Load both files
            template_content = source.read_text(encoding="utf-8")
            template_content = replace_placeholders(template_content, replacements)
            template_data = json.loads(template_content)

            existing_data = json.loads(dest.read_text(encoding="utf-8"))

            # Deep merge: template defines structure, existing fills values
            merged = deep_merge(template_data, existing_data)

            # Write merged result
            dest.write_text(
                json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            if trace:
                logger.info(f"[update] JSON merged: {branch_path}")
            return "updated"

        except (json.JSONDecodeError, IOError) as exc:
            logger.error(f"[update] JSON merge failed for {branch_path}: {exc}")
            return "skipped"

    # Other file types — skip (don't overwrite)
    if trace:
        logger.info(f"[update] SKIPPED non-JSON non-py file: {branch_path}")
    return "skipped"


def _execute_prune(branch_dir: Path, prune_info: dict, trace: bool) -> None:
    """Archive a pruned file to .archive/ within the branch."""
    branch_path = prune_info.get("branch_path", "")
    if not branch_path:
        return

    source = branch_dir / branch_path
    if not source.exists():
        if trace:
            logger.info(f"[update] Pruned file already gone: {branch_path}")
        return

    # Archive destination
    archive_dir = branch_dir / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Use flat name with path separators replaced to avoid collisions
    archive_name = branch_path.replace("/", "__").replace("\\", "__")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dest = archive_dir / f"{archive_name}.{timestamp}.pruned"

    if source.is_file():
        shutil.move(str(source), str(archive_dest))
    elif source.is_dir():
        shutil.move(str(source), str(archive_dest))

    if trace:
        logger.info(f"[update] Archived: {branch_path} -> .archive/{archive_dest.name}")


# =============================================================================
# RESULT HELPERS
# =============================================================================

def _result(
    branch_name: str,
    success: bool,
    counts: dict,
    errors: list[str],
    dry_run: bool,
    **extra: Any,
) -> dict:
    """Build a standardized result dict."""
    result = {
        "branch": branch_name,
        "success": success,
        "additions": counts.get("additions", 0),
        "renames": counts.get("renames", 0),
        "updates": counts.get("updates", 0),
        "pruned": counts.get("pruned", 0),
        "skipped_py": counts.get("skipped_py", 0),
        "errors": errors,
        "dry_run": dry_run,
    }
    result.update(extra)
    return result
