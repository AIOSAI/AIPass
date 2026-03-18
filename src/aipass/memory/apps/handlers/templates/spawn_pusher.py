# =================== AIPass ====================
# Name: spawn_pusher.py
# Description: Spawn Template Sync Handler
# Version: 0.1.0
# Created: 2026-03-15
# Modified: 2026-03-15
# =============================================

"""
Spawn Template Sync Handler

Pushes memory's canonical template updates to spawn's template factory
so that newly created branches always get the latest schema.

Purpose:
    Memory owns the living templates (LOCAL.template.json, OBSERVATIONS.template.json).
    Spawn has multiple template sets (birthright, builder, etc.) each containing
    a .trinity/ directory with local.json and observations.json. This handler
    auto-discovers spawn's template sets and propagates structural changes from
    memory's canonical templates, preserving {{BRANCHNAME}} and {{DATE}} placeholders.

Independence:
    Self-contained handler. Reads/writes JSON files directly with pathlib.
    No imports from other handlers.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from aipass.prax import logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

# =============================================================================
# PATH SETUP
# =============================================================================

# handlers/templates/spawn_pusher.py -> apps/handlers/templates/ (3 levels up = memory/)
MEMORY_ROOT = Path(__file__).resolve().parent.parent.parent.parent

TEMPLATES_DIR = MEMORY_ROOT / "templates"
LOCAL_TEMPLATE_PATH = TEMPLATES_DIR / "LOCAL.template.json"
OBS_TEMPLATE_PATH = TEMPLATES_DIR / "OBSERVATIONS.template.json"


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def _find_spawn_templates_dir() -> Path:
    """Locate spawn's templates directory relative to repo root."""
    repo_root = _find_repo_root()
    return repo_root / "src" / "aipass" / "spawn" / "templates"


# =============================================================================
# TEMPLATE SET DISCOVERY
# =============================================================================

def _discover_template_sets(spawn_templates_dir: Path) -> List[Dict[str, Any]]:
    """
    Auto-discover spawn template sets that contain a .trinity/ directory.

    Skips .archive/ and any hidden directories.

    Returns:
        List of dicts with 'name' and 'trinity_path' keys.
    """
    template_sets = []

    if not spawn_templates_dir.is_dir():
        return template_sets

    for child in sorted(spawn_templates_dir.iterdir()):
        if not child.is_dir():
            continue
        # Skip hidden dirs and .archive
        if child.name.startswith("."):
            continue
        trinity_dir = child / ".trinity"
        if trinity_dir.is_dir():
            template_sets.append({
                "name": child.name,
                "trinity_path": trinity_dir,
            })

    return template_sets


# =============================================================================
# JSON COMPARISON
# =============================================================================

def _read_json(path: Path) -> dict | None:
    """Read and parse a JSON file. Returns None on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_json(path: Path, data: dict) -> bool:
    """Write dict as pretty-printed JSON. Returns True on success."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except OSError:
        return False


def _json_equal(a: dict | None, b: dict | None) -> bool:
    """Structural equality check for two JSON objects."""
    if a is None or b is None:
        return False
    return a == b


# =============================================================================
# MAIN PUSH FUNCTION
# =============================================================================

def push_to_spawn_templates(dry_run: bool = False) -> dict:
    """
    Push memory's canonical templates to spawn's template directories.

    Auto-discovers template sets under spawn/templates/ that contain
    a .trinity/ directory. Compares memory's canonical LOCAL.template.json
    and OBSERVATIONS.template.json against each set's local.json and
    observations.json. Writes updates when structural differences are found.

    Placeholders ({{BRANCHNAME}}, {{DATE}}) are preserved as-is since
    spawn resolves them at branch-creation time.

    Args:
        dry_run: If True, report what would change without writing files.

    Returns:
        Result dict with template_sets_found, template_sets_updated,
        files_modified, changes, and errors.
    """
    result: Dict[str, Any] = {
        "success": True,
        "dry_run": dry_run,
        "template_sets_found": [],
        "template_sets_updated": 0,
        "files_modified": 0,
        "changes": [],
        "errors": [],
    }

    # --- Load canonical templates from memory ---
    canonical_local = _read_json(LOCAL_TEMPLATE_PATH)
    if canonical_local is None:
        result["success"] = False
        result["errors"].append(f"Failed to read canonical LOCAL template: {LOCAL_TEMPLATE_PATH}")
        return result

    canonical_obs = _read_json(OBS_TEMPLATE_PATH)
    if canonical_obs is None:
        result["success"] = False
        result["errors"].append(f"Failed to read canonical OBSERVATIONS template: {OBS_TEMPLATE_PATH}")
        return result

    # --- Locate spawn templates directory ---
    spawn_templates_dir = _find_spawn_templates_dir()
    if not spawn_templates_dir.is_dir():
        result["success"] = False
        result["errors"].append(f"Spawn templates directory not found: {spawn_templates_dir}")
        return result

    # --- Discover template sets ---
    template_sets = _discover_template_sets(spawn_templates_dir)
    result["template_sets_found"] = [ts["name"] for ts in template_sets]

    if not template_sets:
        logger.info("spawn_pusher: No template sets found with .trinity/ directories")
        return result

    # --- Compare and push each template set ---
    file_map = [
        ("local.json", canonical_local),
        ("observations.json", canonical_obs),
    ]

    for ts in template_sets:
        ts_name = ts["name"]
        trinity_path = ts["trinity_path"]
        set_changed = False

        for filename, canonical in file_map:
            spawn_file = trinity_path / filename
            existing = _read_json(spawn_file) if spawn_file.exists() else None

            if _json_equal(existing, canonical):
                continue  # Already in sync

            # Determine action label
            action = "updated" if spawn_file.exists() else "created"
            set_changed = True
            result["files_modified"] += 1
            result["changes"].append({
                "template_set": ts_name,
                "file": filename,
                "action": action,
            })

            if not dry_run:
                if not _write_json(spawn_file, canonical):
                    result["errors"].append(
                        f"{ts_name}: Failed to write {filename}"
                    )

        if set_changed:
            result["template_sets_updated"] += 1

    # --- Summary logging ---
    mode = "DRY RUN" if dry_run else "PUSH"
    logger.info(
        f"spawn_pusher [{mode}]: "
        f"{len(template_sets)} sets found, "
        f"{result['template_sets_updated']} updated, "
        f"{result['files_modified']} files modified"
    )

    log_operation("spawn_template_push", {"sets_updated": result["template_sets_updated"], "files": result["files_modified"], "dry_run": dry_run, "success": True})
    return result


# =============================================================================
# CLI INTERFACE
# =============================================================================

if __name__ == "__main__":
    import sys as _sys

    _out = _sys.stdout.write
    args = _sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        _out("Usage: python3 spawn_pusher.py [push|push --dry-run]\n\n")
        _out("Commands:\n")
        _out("  push           Push canonical templates to spawn template sets\n")
        _out("  push --dry-run Preview changes without writing\n")
        _sys.exit(1)

    command = args[0]

    if command == "push":
        dry = "--dry-run" in args
        push_result = push_to_spawn_templates(dry_run=dry)
        mode = "DRY RUN" if push_result.get("dry_run") else "PUSH"
        _out(f"\n=== Spawn Template {mode} Results ===\n")
        _out(f"Template sets found:   {', '.join(push_result['template_sets_found']) or 'none'}\n")
        _out(f"Template sets updated: {push_result['template_sets_updated']}\n")
        _out(f"Files modified:        {push_result['files_modified']}\n")
        if push_result["changes"]:
            _out(f"\nChanges ({len(push_result['changes'])} files):\n")
            for entry in push_result["changes"]:
                _out(f"  {entry['template_set']}/.trinity/{entry['file']}: {entry['action']}\n")
        if push_result["errors"]:
            _out(f"\nErrors ({len(push_result['errors'])}):\n")
            for err in push_result["errors"]:
                _out(f"  ! {err}\n")
        if not push_result["changes"] and not push_result["errors"]:
            _out("\nAll spawn template sets are in sync with canonical templates.\n")
        _out("\n")
        _sys.exit(0 if push_result["success"] else 1)
    else:
        _out(f"Unknown command: {command}\n")
        _out("Usage: python3 spawn_pusher.py [push|push --dry-run]\n")
        _sys.exit(1)
