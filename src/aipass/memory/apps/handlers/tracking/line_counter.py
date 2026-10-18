# =================== AIPass ====================
# Name: line_counter.py
# Description: Memory File Line Counter Handler
# Version: 0.2.1
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""
Line Counter Handler
"""

from pathlib import Path
from typing import Dict, Any

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()


def _count_physical_lines(file_path: Path) -> int:
    """Count physical lines in file"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return len(f.readlines())
    except Exception as e:
        logger.warning(f"[line_counter] Failed to count lines in {file_path}: {e}")
        return 0


def update_line_count(file_path: Path) -> Dict[str, Any]:
    """Count the physical lines of a memory file and report them; reads only, writes nothing."""
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    line_count = _count_physical_lines(file_path)

    json_handler.log_operation("update_line_count", {"file": file_path.name, "lines": line_count, "success": True})

    return {"success": True, "file": str(file_path), "lines": line_count}


def update_all_memory_files() -> Dict[str, Any]:
    """Update line counts for all memory files in AIPASS_REGISTRY; an unreadable registry returns success False."""
    from aipass.memory.apps.handlers.monitor.detector import RegistryUnreadable, _read_registry, _get_memory_file_path

    try:
        branches = _read_registry()
    except RegistryUnreadable as e:
        logger.error(f"[line_counter] {e}")
        return {"success": False, "error": str(e)}
    if not branches:
        return {"success": True, "updated": 0, "failed": 0, "message": "No branches in registry"}

    updated = 0
    failed = []

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")

        for memory_type in ["observations", "local"]:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue

            result = update_line_count(file_path)

            if result["success"]:
                updated += 1
            else:
                failed.append((branch_name, memory_type, result.get("error")))

    return {"success": True, "updated": updated, "failed": len(failed), "failures": failed}
