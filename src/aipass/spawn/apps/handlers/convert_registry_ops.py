# =================== AIPass ====================
# Name: convert_registry_ops.py
# Description: Convert one registry to the stored shape: lowercase names, paths relative to its folder
# Version: 1.0.0
# Created: 2026-11-22
# Modified: 2026-11-22
# =============================================

"""Convert one *_REGISTRY.json in place: every row name lowercase, every path relative to the registry's folder.

Reference: docs/registry_and_repair.md
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

from aipass.prax import logger

from aipass.spawn.apps.handlers.atomic_write import atomic_write_text
from aipass.spawn.apps.handlers.json import json_handler
from aipass.spawn.apps.handlers.metadata import normalize_branch_name
from aipass.spawn.apps.handlers.registry import registry_lock

REBUILD_CURE = "drone @spawn sync-registry --rebuild"


def _plan_rows(branches, root: Path):
    """Each row's (key, row, old name, new name, old path, new path); a refusal string when one cannot convert."""
    items = list(branches.items()) if isinstance(branches, dict) else [(None, row) for row in branches]
    folded: dict[str, str] = {}
    plan = []
    for key, row in items:
        if not isinstance(row, dict):
            return f"row {key if key is not None else row!r} is not an object"
        old_name = str(row.get("name", key or ""))
        new_name = normalize_branch_name(old_name)
        if new_name in folded:
            return (
                f"rows '{folded[new_name]}' and '{old_name}' fold to one name '{new_name}'; "
                "choose which row lives, then run this again"
            )
        folded[new_name] = old_name
        old_path = str(row.get("path", ""))
        new_path = old_path
        if old_path:
            resolved = (root / old_path).resolve()
            if not resolved.is_relative_to(root):
                return f"row '{old_name}': path {old_path} is outside the registry's folder {root}"
            if Path(old_path).is_absolute():
                new_path = resolved.relative_to(root).as_posix()
        plan.append((key, row, old_name, new_name, old_path, new_path))
    return plan


def convert_registry(registry_path, confirm=False) -> dict:
    """Lowercase every row name and relativize every absolute path; a preview unless confirm.

    Refused, nothing written: a missing or unreadable file, two rows folding to one name, a path outside
    the registry's folder. Row order and every other key are kept; metadata gains only last_updated.
    With confirm a byte copy is written beside the registry first. Returns a receipt:
    refused, changes [{old_name, new_name, old_path, new_path}], copy, written."""
    registry_path = Path(registry_path)
    root = registry_path.resolve().parent
    receipt = {"registry": str(registry_path), "refused": None, "changes": [], "copy": None, "written": False}

    def _refuse(reason):
        logger.error("[convert-registry] %s", reason)
        receipt["refused"] = f"{reason} - nothing written"
        return receipt

    with registry_lock(registry_path):
        if not registry_path.is_file():
            return _refuse(f"{registry_path} does not exist")
        try:
            document = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return _refuse(f"{registry_path.name} does not parse ({exc}); a corrupt one is rebuilt: {REBUILD_CURE}")
        branches = document.get("branches", []) if isinstance(document, dict) else None
        if not isinstance(branches, (list, dict)):
            return _refuse(f"{registry_path.name} has no branches list or object; {REBUILD_CURE}")

        plan = _plan_rows(branches, root)
        if isinstance(plan, str):
            return _refuse(plan)
        receipt["changes"] = [
            {"old_name": old_name, "new_name": new_name, "old_path": old_path, "new_path": new_path}
            for key, _row, old_name, new_name, old_path, new_path in plan
            if (old_name, old_path) != (new_name, new_path) or key not in (None, new_name)
        ]
        if not confirm or not receipt["changes"]:
            return receipt

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        copy = registry_path.with_name(f"{registry_path.name}.pre-convert-{stamp}")
        shutil.copy2(registry_path, copy)
        receipt["copy"] = str(copy)

        for _key, row, _old, new_name, _op, new_path in plan:
            if "name" in row:
                row["name"] = new_name
            if "path" in row:
                row["path"] = new_path
        if isinstance(branches, dict):
            document["branches"] = {new_name: row for _key, row, _old, new_name, _op, _np in plan}
        if isinstance(document.get("metadata"), dict):
            document["metadata"]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
        atomic_write_text(registry_path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
        receipt["written"] = True
        converted = len(receipt["changes"])
        logger.info("[convert-registry] Converted %d row(s) in %s; copy at %s", converted, registry_path, copy)
        json_handler.log_operation("registry_converted", data={"registry": str(registry_path), "rows": converted})
    return receipt
