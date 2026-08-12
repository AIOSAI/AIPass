# =================== AIPass ====================
# Name: normalize.py
# Description: Memory File Schema Normalizer
# Version: 0.4.0
# Created: 2026-01-22
# Modified: 2026-08-12
# =============================================

"""
Memory File Schema Normalizer

Reconciles memory files against their canonical template schema.
Strips any key not present in the template at every level (root,
document_metadata, limits, status). Template = the whole truth.

Also holds the newest-first re-sort guardrail. It never fails open silently:
an entry with an unusable 'number' is reported (result warnings + prax WARNING)
and left at its index while the rows beside it are still ordered.
"""

import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()

_MEMORY_ROOT = Path(__file__).parents[3]  # normalize.py -> schema/ -> handlers/ -> apps/ -> memory/

# Containers held newest-first by contract — rollover archives their tail as "oldest"
_SORTED_CONTAINERS = ("sessions", "key_learnings", "todos", "observations")


def _load_template(file_path: Path) -> Dict[str, Any] | None:
    """Load the matching template for a memory file (local or observations)."""
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
    except Exception as e:
        logger.warning(f"[normalize] Failed to load template {tmpl_path}: {e}")
        return None


def _strip_orphan_keys(data: Dict, allowed: set, level_name: str, changes: list) -> None:
    """Remove keys from data that aren't in the allowed set."""
    orphans = set(data.keys()) - allowed
    for key in orphans:
        del data[key]
        changes.append(f"Stripped orphan '{key}' from {level_name}")


def _read_entry_number(entry: Any) -> int | None:
    """Read an entry's 'number' as an int, or None when it cannot be one.

    Numeric strings and integral floats are readable (they are repaired in
    place by the caller); missing keys, booleans, and anything else are not.
    """
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

    An entry whose 'number' cannot be read keeps its exact index and costs the
    rows beside it nothing; the readable entries are ordered among the slots
    they already occupy. Unreadable rows are always reported (GH #728: this
    guardrail used to skip the whole container silently on a single bad entry).

    Returns the reordered list, or None when the container carries no numbers
    at all — the legitimate shape for todos, which is not a defect.
    """
    numbers = [_read_entry_number(entry) for entry in container]
    slots = [i for i, number in enumerate(numbers) if number is not None]
    unreadable = [i for i, number in enumerate(numbers) if number is None]

    if not slots:
        return None

    # Repair readable-but-wrongly-typed numbers so the container stops degrading
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


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def normalize_memory_file(file_path: Path, dry_run: bool = False) -> Dict[str, Any]:
    """
    Normalize a memory file against its canonical template.

    Args:
        file_path: Path to memory JSON file
        dry_run: If True, report changes without writing

    Returns:
        Dict with success status and changes made
    """
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

    # Ensure document_metadata exists
    if "document_metadata" not in data:
        data["document_metadata"] = {}
        changes.append("Created document_metadata")

    metadata = data["document_metadata"]

    # Legacy fix: move root 'limits' into document_metadata.limits
    if "limits" in data and "limits" not in metadata:
        metadata["limits"] = data.pop("limits")
        changes.append("Moved root 'limits' into document_metadata")
    elif "limits" in data and "limits" in metadata:
        root_limits = data.pop("limits")
        for key, val in root_limits.items():
            if key not in metadata["limits"]:
                metadata["limits"][key] = val
        changes.append("Merged root 'limits' into document_metadata.limits")

    # Legacy fix: move root 'status' into document_metadata.status
    if "status" in data:
        data.pop("status")
        if "status" not in metadata:
            metadata["status"] = {}
        changes.append("Removed redundant root 'status'")

    # Ensure status has required fields
    if "status" not in metadata:
        metadata["status"] = {}

    if "last_health_check" not in metadata["status"]:
        metadata["status"]["last_health_check"] = datetime.now().strftime("%Y-%m-%d")
        changes.append("Added last_health_check")

    # Template-conformance: strip orphan keys at every level
    template = _load_template(file_path)
    if template is not None:
        tmpl_meta = template.get("document_metadata", {})

        # Root level
        _strip_orphan_keys(data, set(template.keys()), "root", changes)

        # document_metadata level
        _strip_orphan_keys(metadata, set(tmpl_meta.keys()), "document_metadata", changes)

        # limits level
        tmpl_limits = tmpl_meta.get("limits", {})
        if "limits" in metadata:
            _strip_orphan_keys(metadata["limits"], set(tmpl_limits.keys()), "limits", changes)

        # status level
        tmpl_status = tmpl_meta.get("status", {})
        if "status" in metadata:
            _strip_orphan_keys(metadata["status"], set(tmpl_status.keys()), "status", changes)

    # Sort list entries newest-first by number (self-heal guardrail)
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

    # Write if changes made and not dry run
    if changes and not dry_run:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
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


def normalize_all_memory_files(dry_run: bool = False) -> Dict[str, Any]:
    """
    Normalize schema for all memory files in AIPASS_REGISTRY.

    Args:
        dry_run: If True, report changes without writing

    Returns:
        Dict with statistics
    """
    # Read registry
    registry_path = _find_repo_root() / "AIPASS_REGISTRY.json"

    if not registry_path.exists():
        return {"success": False, "error": "AIPASS_REGISTRY.json not found"}

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
            branches = registry.get("branches", [])
    except Exception as e:
        logger.warning(f"[normalize] Failed to read registry: {e}")
        return {"success": False, "error": f"Failed to read registry: {e}"}

    results = {
        "success": True,
        "files_checked": 0,
        "files_modified": 0,
        "files_with_warnings": 0,
        "dry_run": dry_run,
        "details": [],
    }

    for branch in branches:
        branch_path = Path(branch.get("path", ""))
        branch_name = branch.get("name", "").upper()

        if not branch_path.exists():
            continue

        # Check both file types
        for memory_type in ["local", "observations"]:
            file_name = f"{branch_name}.{memory_type}.json"
            file_path = branch_path / file_name

            if not file_path.exists():
                continue

            results["files_checked"] += 1
            result = normalize_memory_file(file_path, dry_run=dry_run)

            if not result["success"]:
                continue

            if result.get("changes"):
                results["files_modified"] += 1
            if result.get("warnings"):
                results["files_with_warnings"] += 1
            if result.get("changes") or result.get("warnings"):
                results["details"].append(
                    {
                        "file": file_name,
                        "changes": result["changes"],
                        "warnings": result["warnings"],
                    }
                )

    return results


# CLI entry point
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Normalize memory file schema")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    parser.add_argument("--file", type=str, help="Normalize single file")
    args = parser.parse_args()

    if args.file:
        result = normalize_memory_file(Path(args.file), dry_run=args.dry_run)
        print(json.dumps(result, indent=2))
    else:
        result = normalize_all_memory_files(dry_run=args.dry_run)
        print(f"Files checked: {result['files_checked']}")
        print(f"Files modified: {result['files_modified']}")
        print(f"Files with warnings: {result['files_with_warnings']}")
        if result["details"]:
            print("\nChanges:")
            for detail in result["details"]:
                print(f"  {detail['file']}:")
                for change in detail["changes"]:
                    print(f"    - {change}")
                for warning in detail["warnings"]:
                    print(f"    ! WARNING: {warning}")
