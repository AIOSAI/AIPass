# =================== AIPass ====================
# Name: normalizer.py
# Description: Frame-only re-render for a branch rollover just touched — heals the machine frame, never the entries
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Rollover Normalizer

Frame-only: shares ``trinity_push.build_frame`` so one renderer exists, never
prunes (pruning is the push's, with its gates), and takes ONE branch, no fleet tail.
"""

from pathlib import Path
from typing import Any

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple
from aipass.memory.apps.handlers.templates import trinity_push


def _normalize_file(branch_name: str, trinity: Path, file_key: str, config: dict) -> dict:
    """Re-render one file's frame around its existing entries; branch_name is what ``managed_by`` must equal."""
    path = trinity / trinity_push._FILE_NAMES[file_key]
    if not path.is_file():
        return {"written": False, "error": f"{path.name}: not found", "changes": []}

    before = read_memory_file_data(path)
    if not isinstance(before, dict):
        # Never treated as empty: rebuilding a frame around no entries would
        # delete a branch's whole memory to fix its formatting.
        return {"written": False, "error": f"{path.name}: unreadable or not a JSON object", "changes": []}

    entries: dict[str, list] = {}
    for section in trinity_push._SECTIONS[file_key]:
        raw = before.get(section)
        if raw is None:
            entries[section] = []
            continue
        if not isinstance(raw, list):
            return {
                "written": False,
                "error": f"{path.name}: '{section}' must be a list, found {type(raw).__name__}",
                "changes": [],
            }
        entries[section] = list(raw)

    after = trinity_push.build_frame(before, file_key, branch_name, entries, config)
    changes = trinity_push._frame_changes(before, after, file_key)
    if not write_memory_file_simple(path, after):
        return {"written": False, "error": f"{path.name}: write failed", "changes": changes}
    return {"written": True, "error": None, "changes": changes}


def normalize_branch(branch_name: str, branch_path: Path, config: dict | None = None) -> dict[str, Any]:
    """Re-render ONE branch's machine frame in place. Entries are untouched.

    Never raises: it runs on the tail of a rollover that already succeeded.
    """
    trinity = Path(branch_path) / trinity_push.TRINITY_DIR
    result: dict[str, Any] = {
        "success": False,
        "branch": branch_name,
        "written": 0,
        "changes": {},
        "error": None,
    }

    if not trinity.is_dir():
        result["error"] = f"{branch_name}: no .trinity/ directory at {trinity}"
        logger.warning(f"[normalizer] {result['error']}")
        return result

    if config is None:
        config = config_loader.load()

    errors = []
    for file_key in ("local", "observations"):
        outcome = _normalize_file(branch_name, trinity, file_key, config)
        result["changes"][file_key] = outcome["changes"]
        if outcome["written"]:
            result["written"] += 1
        if outcome["error"]:
            errors.append(outcome["error"])

    result["success"] = result["written"] > 0
    if errors:
        result["error"] = f"{branch_name}: " + "; ".join(errors)
        logger.warning(f"[normalizer] {result['error']}")

    json_handler.log_operation(
        "normalize_branch",
        {"branch": branch_name, "written": result["written"], "errors": len(errors)},
        module_name="normalizer",
    )
    return result
