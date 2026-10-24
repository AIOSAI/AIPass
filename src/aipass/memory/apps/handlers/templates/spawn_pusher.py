# =================== AIPass ====================
# Name: spawn_pusher.py
# Description: Spawn Template Sync Handler
# Version: 0.2.0
# Created: 2026-03-15
# Modified: 2026-10-17
# =============================================

"""
Spawn Template Sync Handler
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from aipass.memory.apps.handlers import repo_root, write_fence
from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file

MEMORY_ROOT = module_file(__file__).parent.parent.parent.parent

TEMPLATES_DIR = MEMORY_ROOT / "templates"
LOCAL_TEMPLATE_PATH = TEMPLATES_DIR / "LOCAL.template.json"
OBS_TEMPLATE_PATH = TEMPLATES_DIR / "OBSERVATIONS.template.json"


def _find_repo_root() -> Path:
    """Repo root for this lane; a local name because tests patch it, the body lives in ``repo_root.py``."""
    return repo_root.find_repo_root(caller="spawn_pusher")


def _find_spawn_templates_dir() -> Path:
    """Locate spawn's templates directory relative to repo root."""
    repo_root = _find_repo_root()
    return repo_root / "src" / "aipass" / "spawn" / "templates"


def _discover_template_sets(spawn_templates_dir: Path) -> List[Dict[str, Any]]:
    """Spawn template sets that contain a .trinity/ directory, hidden ones (.archive/) skipped."""
    template_sets = []

    if not spawn_templates_dir.is_dir():
        return template_sets

    for child in sorted(spawn_templates_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        trinity_dir = child / ".trinity"
        if trinity_dir.is_dir():
            template_sets.append(
                {
                    "name": child.name,
                    "trinity_path": trinity_dir,
                }
            )

    return template_sets


def _read_json(path: Path) -> dict | None:
    """Read and parse a JSON file. Returns None on any error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[spawn_pusher] Failed to read JSON {path}: {e}")
        return None


def _write_json(path: Path, data: dict) -> bool:
    """Write dict as pretty-printed JSON. Returns True on success. Never outside the AIPass root."""
    if write_fence.fence_write(path, lane="spawn_pusher") is not None:
        return False
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        return True
    except OSError as e:
        logger.warning(f"[spawn_pusher] Failed to write JSON {path}: {e}")
        return False


def _json_equal(a: dict | None, b: dict | None) -> bool:
    """Structural equality check for two JSON objects."""
    if a is None or b is None:
        return False
    return a == b


def push_to_spawn_templates(dry_run: bool = False) -> dict:
    """Push memory's canonical templates to every spawn template set that differs.

    Placeholders ({{BRANCH}}, {{DATE}}) are copied as-is: spawn resolves them at creation.
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

    spawn_templates_dir = _find_spawn_templates_dir()
    if not spawn_templates_dir.is_dir():
        result["success"] = False
        result["errors"].append(f"Spawn templates directory not found: {spawn_templates_dir}")
        return result

    template_sets = _discover_template_sets(spawn_templates_dir)
    result["template_sets_found"] = [ts["name"] for ts in template_sets]

    if not template_sets:
        logger.info("spawn_pusher: No template sets found with .trinity/ directories")
        return result

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

            action = "updated" if spawn_file.exists() else "created"
            set_changed = True
            result["files_modified"] += 1
            result["changes"].append(
                {
                    "template_set": ts_name,
                    "file": filename,
                    "action": action,
                }
            )

            if not dry_run:
                if not _write_json(spawn_file, canonical):
                    result["errors"].append(f"{ts_name}: Failed to write {filename}")

        if set_changed:
            result["template_sets_updated"] += 1

    mode = "DRY RUN" if dry_run else "PUSH"
    logger.info(
        f"spawn_pusher [{mode}]: "
        f"{len(template_sets)} sets found, "
        f"{result['template_sets_updated']} updated, "
        f"{result['files_modified']} files modified"
    )

    json_handler.log_operation(
        "spawn_template_push",
        {
            "sets_updated": result["template_sets_updated"],
            "files": result["files_modified"],
            "dry_run": dry_run,
            "success": True,
        },
    )
    return result
