# =================== AIPass ====================
# Name: pusher.py
# Description: Living Template Push Handler
# Version: 0.2.0
# Created: 2026-02-14
# Modified: 2026-03-15
# =============================================

"""
Living Template Push Handler

Pushes structural template updates to ALL registered branch memory files.
Updates metadata, limits, status fields, notes, and guidelines without
touching content (sessions, observations, key_learnings entries).

Purpose:
    When templates evolve (new fields, deprecated sections, schema bumps),
    this handler propagates those structural changes system-wide while
    preserving each branch's unique content and per-branch overrides.

Independence:
    Uses json_handler for safe reads/writes. Loads AIPASS_REGISTRY.json
    and templates directly. No service or module dependencies.
"""

import json
import copy
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime

from aipass.prax import logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

# Handler imports (same-branch allowed per handler boundaries)
from aipass.memory.apps.handlers.json.memory_files import (
    read_memory_file_data,
    write_memory_file_simple
)

# =============================================================================
# PATH SETUP
# =============================================================================

MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent  # handlers/templates/pusher.py -> memory/


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()

# =============================================================================
# CONSTANTS
# =============================================================================

REGISTRY_PATH = _REPO_ROOT / "AIPASS_REGISTRY.json"
TEMPLATES_DIR = MEMORY_ROOT / "templates"
LOCAL_TEMPLATE_PATH = TEMPLATES_DIR / "LOCAL.template.json"
OBS_TEMPLATE_PATH = TEMPLATES_DIR / "OBSERVATIONS.template.json"
VERSION_FILE_PATH = TEMPLATES_DIR / ".template_version.json"

# Deprecated sections to REMOVE during push
DEPRECATED_METADATA_KEYS = ["allowed_emojis"]
DEPRECATED_LIMIT_KEYS = ["max_word_count", "max_token_count"]
DEPRECATED_STATUS_KEYS = ["auto_compress_at"]
DEPRECATED_NOTES_KEYS = ["formatting_reference", "slash_command_tracking"]
DEPRECATED_GUIDELINES_KEYS = ["emoji_usage", "high_value_patterns", "low_value_patterns"]


# =============================================================================
# PLACEHOLDER REPLACEMENT
# =============================================================================

def _replace_placeholders(template: dict, branch_name: str) -> dict:
    """Replace {{BRANCHNAME}} and {{DATE}} in template values. Returns new dict."""
    today = datetime.now().strftime("%Y-%m-%d")

    def _walk(val: Any) -> Any:
        if isinstance(val, str):
            return val.replace("{{BRANCHNAME}}", branch_name).replace("{{DATE}}", today)
        elif isinstance(val, list):
            return [_walk(item) for item in val]
        elif isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    result = _walk(copy.deepcopy(template))
    assert isinstance(result, dict)
    return result


# =============================================================================
# DEPRECATED SECTION REMOVAL
# =============================================================================

def _remove_deprecated(data: dict, file_type: str) -> List[str]:
    """Remove deprecated sections from data (in-place). Returns list of changes."""
    changes = []
    metadata = data.get("document_metadata", {})

    for key in DEPRECATED_METADATA_KEYS:
        if key in metadata:
            del metadata[key]
            changes.append(f"removed document_metadata.{key}")

    for key in DEPRECATED_LIMIT_KEYS:
        if key in metadata.get("limits", {}):
            del metadata["limits"][key]
            changes.append(f"removed document_metadata.limits.{key}")

    for key in DEPRECATED_STATUS_KEYS:
        if key in metadata.get("status", {}):
            del metadata["status"][key]
            changes.append(f"removed document_metadata.status.{key}")

    notes = data.get("notes", {})
    if isinstance(notes, dict):
        for key in DEPRECATED_NOTES_KEYS:
            if key in notes:
                del notes[key]
                changes.append(f"removed notes.{key}")

    if file_type == "observations":
        guidelines = data.get("guidelines", {})
        if isinstance(guidelines, dict):
            for key in DEPRECATED_GUIDELINES_KEYS:
                if key in guidelines:
                    del guidelines[key]
                    changes.append(f"removed guidelines.{key}")

    return changes


# =============================================================================
# SHARED METADATA MERGE
# =============================================================================

def _merge_metadata(curr_meta: dict, tmpl_meta: dict) -> List[str]:
    """
    Merge template metadata into current metadata (in-place).
    Preserves per-branch max_lines overrides and current status values.
    Returns list of changes.
    """
    changes = []

    # Version and schema
    for key in ["version", "schema_version", "document_type"]:
        tmpl_val = tmpl_meta.get(key)
        if tmpl_val and curr_meta.get(key) != tmpl_val:
            old = curr_meta.get(key, "<missing>")
            curr_meta[key] = tmpl_val
            changes.append(f"document_metadata.{key}: {old} -> {tmpl_val}")

    # Tags
    tmpl_tags = tmpl_meta.get("tags", [])
    if tmpl_tags and set(curr_meta.get("tags", [])) != set(tmpl_tags):
        curr_meta["tags"] = tmpl_tags
        changes.append("document_metadata.tags: updated to template tags")

    # Limits (preserve per-branch max_lines override)
    tmpl_limits = tmpl_meta.get("limits", {})
    curr_limits = curr_meta.get("limits", {})
    branch_max_lines = curr_limits.get("max_lines")
    tmpl_max_lines = tmpl_limits.get("max_lines", 600)
    new_limits = copy.deepcopy(tmpl_limits)
    if branch_max_lines is not None and branch_max_lines != tmpl_max_lines:
        new_limits["max_lines"] = branch_max_lines
    if curr_limits != new_limits:
        curr_meta["limits"] = new_limits
        changes.append("document_metadata.limits: updated from template")

    # Status (add missing fields, preserve current values)
    curr_status = curr_meta.setdefault("status", {})
    for key, default_val in tmpl_meta.get("status", {}).items():
        if key not in curr_status:
            curr_status[key] = default_val
            changes.append(f"document_metadata.status.{key}: added (default: {default_val})")

    # Rollover history (deprecated - remove if present)
    if "rollover_history" in curr_meta:
        del curr_meta["rollover_history"]
        changes.append("document_metadata.rollover_history: removed (deprecated)")

    return changes


# =============================================================================
# STRUCTURAL MERGE: LOCAL FILES
# =============================================================================

def _apply_template_to_local(current: dict, template: dict, branch_name: str) -> Tuple[dict, List[str]]:
    """Apply LOCAL template structural updates. Returns (updated_dict, list_of_changes)."""
    changes = []
    data = copy.deepcopy(current)
    curr_meta = data.setdefault("document_metadata", {})
    tmpl_meta = template.get("document_metadata", {})

    # Metadata merge (shared logic)
    changes.extend(_merge_metadata(curr_meta, tmpl_meta))

    # Notes: replace with template notes
    tmpl_notes = template.get("notes", {})
    if isinstance(tmpl_notes, dict) and data.get("notes", {}) != tmpl_notes:
        data["notes"] = copy.deepcopy(tmpl_notes)
        changes.append("notes: updated from template")

    # Key learnings: add if missing (check legacy location too)
    if "key_learnings" not in data:
        active = data.get("active_tasks", {})
        if not isinstance(active, dict) or "key_learnings" not in active:
            data["key_learnings"] = {}
            changes.append("key_learnings: added (empty)")

    # Active tasks: ensure recently_completed exists
    if "active_tasks" in data and isinstance(data["active_tasks"], dict):
        if "recently_completed" not in data["active_tasks"]:
            data["active_tasks"]["recently_completed"] = []
            changes.append("active_tasks.recently_completed: added (empty)")

    # Narrative: only replace if still a placeholder
    curr_narrative = data.get("narrative", "")
    if isinstance(curr_narrative, str) and "{{PLACEHOLDER}}" in curr_narrative:
        data["narrative"] = template.get("narrative", "")
        changes.append("narrative: replaced placeholder with template")

    # Remove deprecated sections
    changes.extend(_remove_deprecated(data, "local"))
    return data, changes


# =============================================================================
# STRUCTURAL MERGE: OBSERVATIONS FILES
# =============================================================================

def _apply_template_to_observations(current: dict, template: dict, branch_name: str) -> Tuple[dict, List[str]]:
    """Apply OBSERVATIONS template structural updates. Returns (updated_dict, list_of_changes)."""
    changes = []
    data = copy.deepcopy(current)
    curr_meta = data.setdefault("document_metadata", {})
    tmpl_meta = template.get("document_metadata", {})

    # Metadata merge (shared logic)
    changes.extend(_merge_metadata(curr_meta, tmpl_meta))

    # Guidelines: replace with template guidelines
    tmpl_guidelines = template.get("guidelines", {})
    if isinstance(tmpl_guidelines, dict) and data.get("guidelines", {}) != tmpl_guidelines:
        data["guidelines"] = copy.deepcopy(tmpl_guidelines)
        changes.append("guidelines: updated from template")

    # Notes: replace with template notes
    tmpl_notes = template.get("notes", {})
    if isinstance(tmpl_notes, dict) and data.get("notes", {}) != tmpl_notes:
        data["notes"] = copy.deepcopy(tmpl_notes)
        changes.append("notes: updated from template")

    # Narrative: only replace if still a placeholder
    curr_narrative = data.get("narrative", "")
    if isinstance(curr_narrative, str) and "{{PLACEHOLDER}}" in curr_narrative:
        data["narrative"] = template.get("narrative", "")
        changes.append("narrative: replaced placeholder with template")

    # Remove deprecated sections
    changes.extend(_remove_deprecated(data, "observations"))
    return data, changes


# =============================================================================
# BRANCH DISCOVERY
# =============================================================================

def _load_registry() -> Optional[List[Dict[str, Any]]]:
    """Load branch registry and return list of active branches."""
    if not REGISTRY_PATH.exists():
        return None
    try:
        with open(REGISTRY_PATH, 'r', encoding='utf-8') as f:
            registry = json.load(f)
        branches = registry.get("branches", [])
        # Resolve relative paths against repo root
        for branch in branches:
            raw_path = branch.get('path', '')
            resolved = Path(raw_path)
            if not resolved.is_absolute():
                resolved = _REPO_ROOT / raw_path
            branch['path'] = str(resolved)
        return [b for b in branches if b.get("status") == "active"]
    except (json.JSONDecodeError, KeyError):
        return None


def _find_memory_files(branch_path: Path) -> Dict[str, List[Path]]:
    """Find memory files for a branch (excludes DASHBOARD and hidden/backup files)."""
    result: Dict[str, List[Path]] = {"local": [], "observations": []}
    if not branch_path.exists() or not branch_path.is_dir():
        return result
    for f in branch_path.iterdir():
        if f.name.startswith("DASHBOARD") or f.name.startswith(".backup"):
            continue
        if f.suffix != ".json":
            continue
        if f.name.endswith(".local.json"):
            result["local"].append(f)
        elif f.name.endswith(".observations.json"):
            result["observations"].append(f)
    return result


# =============================================================================
# TEMPLATE LOADING
# =============================================================================

def _load_templates() -> Optional[Dict[str, dict]]:
    """Load living templates from Memory Bank templates directory."""
    templates = {}
    for name, path in [("local", LOCAL_TEMPLATE_PATH), ("observations", OBS_TEMPLATE_PATH)]:
        if not path.exists():
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                templates[name] = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
    return templates


# =============================================================================
# MAIN PUSH FUNCTION
# =============================================================================

def push_templates(dry_run: bool = False) -> dict:
    """
    Push living templates to all registered branches.

    Updates STRUCTURAL sections only (metadata, limits, status fields, notes,
    guidelines). Removes deprecated sections. Never touches content (sessions,
    observations, key_learnings, active_tasks entries, narrative).

    Args:
        dry_run: If True, report what would change without writing

    Returns:
        dict with branches_scanned, branches_updated, files_modified,
        changes summary, and errors
    """
    result = {
        "success": True,
        "dry_run": dry_run,
        "branches_scanned": 0,
        "branches_updated": 0,
        "files_modified": 0,
        "changes": [],
        "errors": [],
        "branches_list": []
    }

    templates = _load_templates()
    if templates is None:
        result["success"] = False
        result["errors"].append("Failed to load templates")
        return result

    branches = _load_registry()
    if branches is None:
        result["success"] = False
        result["errors"].append("Failed to load branch registry")
        return result

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")
        branch_path = Path(branch.get("path", ""))
        result["branches_scanned"] += 1
        branch_changed = False
        files = _find_memory_files(branch_path)

        # Process .local.json files
        for local_file in files["local"]:
            current_data = read_memory_file_data(local_file)
            if current_data is None:
                result["errors"].append(f"{branch_name}: Failed to read {local_file.name}")
                continue
            local_tmpl = _replace_placeholders(templates["local"], branch_name)
            updated, changes = _apply_template_to_local(current_data, local_tmpl, branch_name)
            if changes:
                branch_changed = True
                result["files_modified"] += 1
                result["changes"].append({"branch": branch_name, "file": local_file.name, "changes": changes})
                if not dry_run:
                    if not write_memory_file_simple(local_file, updated):
                        result["errors"].append(f"{branch_name}: Failed to write {local_file.name}")

        # Process .observations.json files
        for obs_file in files["observations"]:
            current_data = read_memory_file_data(obs_file)
            if current_data is None:
                result["errors"].append(f"{branch_name}: Failed to read {obs_file.name}")
                continue
            obs_tmpl = _replace_placeholders(templates["observations"], branch_name)
            updated, changes = _apply_template_to_observations(current_data, obs_tmpl, branch_name)
            if changes:
                branch_changed = True
                result["files_modified"] += 1
                result["changes"].append({"branch": branch_name, "file": obs_file.name, "changes": changes})
                if not dry_run:
                    if not write_memory_file_simple(obs_file, updated):
                        result["errors"].append(f"{branch_name}: Failed to write {obs_file.name}")

        if branch_changed:
            result["branches_updated"] += 1
            result["branches_list"].append(branch_name)

    if not dry_run and result["files_modified"] > 0:
        if not _update_version_file(result["branches_list"]):
            result["errors"].append("Failed to update template version file")

    log_operation("template_push", {"branches": result["branches_updated"], "files": result["files_modified"], "dry_run": dry_run, "success": True})
    return result


# =============================================================================
# VERSION TRACKING
# =============================================================================

def _update_version_file(branches_pushed: List[str]) -> bool:
    """Update .template_version.json with push record."""
    try:
        version_data = {}
        if VERSION_FILE_PATH.exists():
            with open(VERSION_FILE_PATH, 'r', encoding='utf-8') as f:
                version_data = json.load(f)
        version_data["last_push"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        version_data["last_push_branches"] = branches_pushed
        with open(VERSION_FILE_PATH, 'w', encoding='utf-8') as f:
            json.dump(version_data, f, indent=2, ensure_ascii=False)
            f.write('\n')
        return True
    except Exception:
        return False


def get_template_status() -> dict:
    """Get current template version and push status."""
    status = {
        "version_file": str(VERSION_FILE_PATH),
        "templates_dir": str(TEMPLATES_DIR),
        "local_template_exists": LOCAL_TEMPLATE_PATH.exists(),
        "observations_template_exists": OBS_TEMPLATE_PATH.exists(),
        "version": None,
        "last_push": None,
        "last_push_branches": []
    }
    if VERSION_FILE_PATH.exists():
        try:
            with open(VERSION_FILE_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            status["version"] = data.get("version")
            status["last_push"] = data.get("last_push")
            status["last_push_branches"] = data.get("last_push_branches", [])
        except (json.JSONDecodeError, IOError):
            status["version"] = "error reading version file"
    return status


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == '__main__':
    import sys as _sys
    _out = _sys.stdout.write

    args = _sys.argv[1:]
    if not args:
        _out("Usage: python3 pusher.py [push|push --dry-run|status]\n\n")
        _out("Commands:\n")
        _out("  push           Push template updates to all branches\n")
        _out("  push --dry-run Preview changes without writing\n")
        _out("  status         Show template version and last push info\n")
        _sys.exit(1)

    command = args[0]

    if command == "push":
        dry_run = "--dry-run" in args
        push_result = push_templates(dry_run=dry_run)
        mode = "DRY RUN" if push_result.get("dry_run") else "PUSH"
        _out(f"\n=== Template {mode} Results ===\n")
        _out(f"Branches scanned:  {push_result['branches_scanned']}\n")
        _out(f"Branches updated:  {push_result['branches_updated']}\n")
        _out(f"Files modified:    {push_result['files_modified']}\n")
        if push_result["changes"]:
            _out(f"\nChanges ({len(push_result['changes'])} files):\n")
            for entry in push_result["changes"]:
                _out(f"\n  {entry['branch']}/{entry['file']}:\n")
                for chg in entry["changes"]:
                    _out(f"    - {chg}\n")
        if push_result["errors"]:
            _out(f"\nErrors ({len(push_result['errors'])}):\n")
            for err in push_result["errors"]:
                _out(f"  ! {err}\n")
        if not push_result["changes"] and not push_result["errors"]:
            _out("\nAll branches are up to date with templates.\n")
        _out("\n")
        _sys.exit(0 if push_result["success"] else 1)

    elif command == "status":
        tmpl_status = get_template_status()
        _out("\n=== Template Status ===\n")
        _out(f"Templates dir:     {tmpl_status['templates_dir']}\n")
        _out(f"LOCAL template:    {'found' if tmpl_status['local_template_exists'] else 'MISSING'}\n")
        _out(f"OBS template:      {'found' if tmpl_status['observations_template_exists'] else 'MISSING'}\n")
        _out(f"Schema version:    {tmpl_status.get('version', 'unknown')}\n")
        _out(f"Last push:         {tmpl_status.get('last_push', 'never')}\n")
        pushed = tmpl_status.get("last_push_branches", [])
        if pushed:
            preview = ', '.join(pushed[:5])
            suffix = '...' if len(pushed) > 5 else ''
            _out(f"Branches pushed:   {len(pushed)} ({preview}{suffix})\n")
        _out("\n")
        _sys.exit(0)

    else:
        _out(f"Unknown command: {command}\n")
        _out("Usage: python3 pusher.py [push|push --dry-run|status]\n")
        _sys.exit(1)
