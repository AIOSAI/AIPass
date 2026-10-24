# =================== AIPass ====================
# Name: normalize.py
# Description: Memory File Schema Normalizer
# Version: 0.6.0
# Created: 2026-01-22
# Modified: 2026-10-17
# =============================================

"""
Memory File Schema Normalizer

Template = the whole truth: any key it does not declare is stripped, at every level.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any

from aipass.memory.apps.handlers import write_fence
from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()

_MEMORY_ROOT = Path(__file__).parents[3]  # normalize.py -> schema/ -> handlers/ -> apps/ -> memory/

# Containers held newest-first by contract — rollover archives their tail as "oldest"
_SORTED_CONTAINERS = ("sessions", "key_learnings", "todos", "observations")


class TemplateUnreadable(ValueError):
    """The gold-source template for a memory file exists in name and cannot be read."""


def _load_template(file_path: Path) -> Dict[str, Any] | None:
    """Load the matching template; None only for a file with no template, TemplateUnreadable if unreadable."""
    templates_dir = _MEMORY_ROOT / "templates"
    name = file_path.name.lower()

    if "local" in name:
        tmpl_path = templates_dir / "LOCAL.template.json"
    elif "observation" in name:
        tmpl_path = templates_dir / "OBSERVATIONS.template.json"
    else:
        return None

    try:
        with open(tmpl_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        raise TemplateUnreadable(f"Unreadable template {tmpl_path}: {e}") from e


def _strip_orphan_keys(data: Dict, allowed: set, level_name: str, changes: list) -> None:
    """Remove keys from data that aren't in the allowed set."""
    orphans = set(data.keys()) - allowed
    for key in orphans:
        del data[key]
        changes.append(f"Stripped orphan '{key}' from {level_name}")


def _read_entry_number(entry: Any) -> int | None:
    """Read an entry's 'number' as an int, or None (booleans are not numbers; numeric strings are)."""
    if not isinstance(entry, dict):
        return None

    value = entry.get("number")

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        candidate = value.strip()
        digits = candidate[1:] if candidate.startswith(("-", "+")) else candidate
        return int(candidate) if digits.isascii() and digits.isdigit() else None
    return None


def _sort_container_newest_first(container: list, container_name: str, changes: list, warnings: list) -> list | None:
    """Order the numbered entries of a container newest-first, tolerating bad rows.

    An unreadable row keeps its index and is always reported; None when no entry has a number
    (ordering only — the write gate names a missing required field).
    """
    numbers = [_read_entry_number(entry) for entry in container]
    slots = [i for i, number in enumerate(numbers) if number is not None]
    unreadable = [i for i, number in enumerate(numbers) if number is None]

    if not slots:
        return None

    for i in slots:
        stored = container[i].get("number")
        if not isinstance(stored, int) or isinstance(stored, bool):
            container[i]["number"] = numbers[i]
            changes.append(f"{container_name}[{i}]: repaired number {stored!r} -> {numbers[i]}")

    if unreadable:
        warnings.append(
            f"{container_name}: {len(unreadable)} entry(ies) at index {unreadable} carry no usable "
            f"'number' — newest-first guardrail ordered the other {len(slots)} only, "
            f"unreadable rows left in place"
        )

    ordered = list(container)
    for slot, entry in zip(slots, sorted((container[i] for i in slots), key=lambda e: e["number"], reverse=True)):
        ordered[slot] = entry

    return ordered


def normalize_memory_file(file_path: Path, dry_run: bool = False) -> Dict[str, Any]:
    """Normalize a memory file against its canonical template."""
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"[normalize] Failed to read {file_path}: {e}")
        return {"success": False, "error": f"Failed to read: {e}"}

    changes = []
    warnings = []

    if "document_metadata" not in data:
        data["document_metadata"] = {}
        changes.append("Created document_metadata")

    metadata = data["document_metadata"]

    if "limits" in data and "limits" not in metadata:
        metadata["limits"] = data.pop("limits")
        changes.append("Moved root 'limits' into document_metadata")
    elif "limits" in data and "limits" in metadata:
        root_limits = data.pop("limits")
        for key, val in root_limits.items():
            if key not in metadata["limits"]:
                metadata["limits"][key] = val
        changes.append("Merged root 'limits' into document_metadata.limits")

    # Dropped, not relocated: health is derived at run time, never stamped into a memory file.
    if "status" in data:
        data.pop("status")
        changes.append("Removed redundant root 'status'")

    try:
        template = _load_template(file_path)
    except TemplateUnreadable as e:
        warnings.append(f"{e} — template conformance skipped")
        template = None
    if template is not None:
        tmpl_meta = template.get("document_metadata", {})

        _strip_orphan_keys(data, set(template.keys()), "root", changes)

        _strip_orphan_keys(metadata, set(tmpl_meta.keys()), "document_metadata", changes)

        tmpl_limits = tmpl_meta.get("limits", {})
        if "limits" in metadata:
            _strip_orphan_keys(metadata["limits"], set(tmpl_limits.keys()), "limits", changes)

        tmpl_status = tmpl_meta.get("status", {})
        if "status" in metadata:
            _strip_orphan_keys(metadata["status"], set(tmpl_status.keys()), "status", changes)

    for container_name in _SORTED_CONTAINERS:
        container = data.get(container_name)
        if not isinstance(container, list) or len(container) <= 1:
            continue

        sorted_entries = _sort_container_newest_first(container, container_name, changes, warnings)
        if sorted_entries is not None and sorted_entries != container:
            data[container_name] = sorted_entries
            changes.append(f"{container_name}: re-sorted by number (newest-first)")

    for warning in warnings:
        logger.warning(f"[normalize] {file_path.name}: {warning}")

    if changes and not dry_run:
        refusal = write_fence.fence_write(file_path, lane="normalize_memory_file")
        if refusal is not None:
            return {"success": False, "error": refusal}
        try:
            tmp = file_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, file_path)
        except Exception as e:
            logger.error(f"[normalize] Failed to write {file_path}: {e}")
            return {"success": False, "error": f"Failed to write: {e}"}

    json_handler.log_operation(
        "normalize_memory_file",
        {"file": file_path.name, "changes": len(changes), "warnings": len(warnings), "success": True},
    )

    return {
        "success": True,
        "file": str(file_path),
        "changes": changes,
        "warnings": warnings,
        "dry_run": dry_run,
    }
