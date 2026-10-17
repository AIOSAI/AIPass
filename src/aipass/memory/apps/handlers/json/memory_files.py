# =================== AIPass ====================
# Name: memory_files.py
# Description: Memory File Safe I/O Handler
# Version: 1.6.0
# Created: 2026-03-17
# Modified: 2026-10-17
# =============================================

"""
Memory File I/O Handler
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json.entry_limits import load_entry_limits, classify_entries
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.write_fence import fence_write

logger = get_system_logger()

_MEMORY_ROOT = module_file(__file__).parents[3]
_CONFIG_DIR = _MEMORY_ROOT / "config"
_TEMPLATES_DIR = _MEMORY_ROOT / "apps" / "json_templates"

_TRACKED_TRINITY_FILES = {"local.json", "observations.json"}


def violation_line(violation: Dict[str, Any]) -> str:
    """Render one violation as a line naming the container, the entry, and what is wrong.

    Each species gets its own words: "0/0 (+0 over)" for an unknown field reads as a gate bug.
    """
    where = f"{violation['container']}[{violation['key']}]"
    reason = violation.get("reason")
    field = violation.get("field", "")
    units = violation.get("units", "chars")

    if reason == "unknown_field":
        return f"{where} field '{field}' is not part of the entry shape"
    if reason == "field_over_cap":
        return f"{where} '{field}' is {violation['length']}/{violation['cap']} {units} (+{violation['over_by']} over)"
    if reason == "missing_field":
        return f"{where} has no '{field}' field"
    if reason == "unmeasurable":
        found = violation.get("found_type", "unknown")
        named = f" '{field}'" if field else ""
        return f"{where}{named} is {found}, expected str"
    return f"{where} {violation['length']}/{violation['cap']} (+{violation['over_by']} over)"


def _validate_entry_limits(
    file_path: Path,
    data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Check entry limits for a tracked .trinity/ write and return a rejection or None.

    A write is judged by what it AUTHORS: entries byte-identical to disk are carried
    debt, never refused, so rollover cannot be blocked by an entry it may not shrink.
    """
    if file_path.parent.name != ".trinity":
        return None
    if file_path.name not in _TRACKED_TRINITY_FILES:
        return None

    branch = file_path.parent.parent.name
    limits = load_entry_limits(branch)

    if not limits.get("enabled", True):
        return None

    filtered_types = {
        name: tdef for name, tdef in limits.get("entry_types", {}).items() if tdef.get("file") == file_path.name
    }
    if not filtered_types:
        return None

    filtered_limits = {
        "enabled": limits["enabled"],
        "enforce": limits["enforce"],
        "entry_types": filtered_types,
    }

    before: Dict[str, Any] = {}
    if file_path.exists():
        try:
            before = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[entry_limits] Could not parse {file_path.name} for diff: {exc}")
            before = {}  # Unparseable — treat as empty (all entries "new")

    split = classify_entries(before, data, filtered_limits)
    over = split["authored"]

    # Carried debt is logged, not passed in silence: an entry that arrived through
    # an ungated lane would otherwise never surface again.
    for debt in split["carried"]:
        logger.warning(
            f"[entry_limits] CARRIED {branch} {file_path.name} "
            f"{violation_line(debt)} — "
            f"not written by this write, not refused; only @{branch} can cure it"
        )

    # Near-cap warns one entry early, authored only: carried near-cap text on every
    # write would turn the channel into noise.
    for close in split["near"]:
        logger.warning(
            f"[entry_limits] NEAR {branch} {file_path.name} "
            f"{close['container']}[{close['key']}] "
            f"{close['length']}/{close['cap']} — "
            f"{close['cap'] - close['length']} chars of headroom left; the next edit may be refused"
        )

    if not over:
        return None

    enforce = limits.get("enforce", False)

    if not enforce:
        for violation in over:
            logger.warning(f"[entry_limits] WARN {branch} {file_path.name} {violation_line(violation)}")
        return None  # Write through in warn mode

    details = "; ".join(violation_line(v) for v in over)
    return {"success": False, "error": f"Entry limit exceeded: {details}"}


def _is_auto_compact(entry: Any) -> bool:
    """True for auto-compact snapshot entries; must match rollover/extractor.py exactly."""
    return isinstance(entry, dict) and entry.get("status") == "auto-compact"


def _warn_entry_count(branch: str, file_name: str, label: str, count: int, cap: int) -> None:
    """Emit one soft-guard warning line for an over-cap section."""
    logger.warning(
        f"[memory_files] ENTRY COUNT: {branch} {file_name} "
        f"{label} has {count}/{cap} entries "
        f"(+{count - cap} over rollover limit)"
    )


def _check_session_counts(branch: str, file_name: str, entries: list, section_cfg: Dict[str, Any]) -> None:
    """Warn on the sessions section, budgeting snapshots separately, as the extractor does."""
    auto_cap = section_cfg.get("auto_compact_cap")
    if auto_cap is not None:
        snapshots = [e for e in entries if _is_auto_compact(e)]
        if len(snapshots) > auto_cap:
            _warn_entry_count(branch, file_name, "sessions(auto-compact)", len(snapshots), auto_cap)

    max_count = section_cfg.get("count")
    if max_count is not None:
        regular = [e for e in entries if not _is_auto_compact(e)]
        if len(regular) > max_count:
            _warn_entry_count(branch, file_name, "sessions", len(regular), max_count)


def _check_entry_counts(file_path: Path, data: Dict[str, Any]) -> None:
    """Soft guard: warn (never block) when list entry counts exceed rollover limits."""
    if file_path.parent.name != ".trinity":
        return
    if file_path.name not in _TRACKED_TRINITY_FILES:
        return

    branch = file_path.parent.parent.name.lower()
    file_type = file_path.stem

    cfg = config_loader.section("rollover")
    per_branch = cfg.get("per_branch", {})
    defaults = cfg.get("defaults", {})

    file_limits = per_branch.get(branch, {}).get(file_type, {})
    if not file_limits:
        file_limits = defaults.get(file_type, {})
    if not file_limits:
        return

    for section_name, section_cfg in file_limits.items():
        if section_name.startswith("_"):
            continue
        if not isinstance(section_cfg, dict):
            continue
        entries = data.get(section_name, [])
        if not isinstance(entries, list):
            continue

        if section_name == "sessions":
            _check_session_counts(branch, file_path.name, entries, section_cfg)
            continue

        max_count = section_cfg.get("count")
        if max_count is not None and len(entries) > max_count:
            _warn_entry_count(branch, file_path.name, section_name, len(entries), max_count)


def read_memory_file(file_path: Path) -> Dict[str, Any]:
    """Safe read of memory JSON file: ``{'success': True, 'data': ...}`` or ``{'success': False, 'error': ...}``."""
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {"success": True, "file": str(file_path), "data": data}

    except json.JSONDecodeError as e:
        logger.warning(f"[memory_files] Corrupt JSON in {file_path.name}: {e}")
        return {"success": False, "error": f"Corrupt JSON in {file_path.name}: {e}"}

    except PermissionError:
        logger.warning(f"[memory_files] Permission denied reading {file_path.name}")
        return {"success": False, "error": f"Permission denied reading {file_path.name}"}

    except Exception as e:
        logger.warning(f"[memory_files] Failed to read {file_path.name}: {e}")
        return {"success": False, "error": f"Failed to read {file_path.name}: {e}"}


def write_memory_file(file_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Atomic write (temp file + rename) of memory JSON; refused outside the AIPass root."""
    refusal = fence_write(file_path, lane="write_memory_file")
    if refusal is not None:
        return {"success": False, "error": refusal}

    if not isinstance(data, dict):
        return {"success": False, "error": f"Data must be dict, got {type(data).__name__}"}

    try:
        rejection = _validate_entry_limits(file_path, data)
        if rejection is not None:
            return rejection
    except Exception as exc:
        logger.warning(f"[memory_files] Entry-limits validation error (writing anyway): {exc}")

    try:
        _check_entry_counts(file_path, data)
    except Exception as exc:
        logger.warning(f"[memory_files] Entry-count check error (writing anyway): {exc}")

    try:
        # Same directory: the rename is only atomic within one filesystem.
        temp_fd, temp_path = tempfile.mkstemp(dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp")

        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")  # Add final newline

            # os.replace, not rename: it overwrites on Windows too.
            os.replace(temp_path, file_path)

            json_handler.log_operation("write_memory_file", {"file": file_path.name, "success": True})

            return {"success": True, "file": str(file_path)}

        except Exception as e:
            logger.error(f"[memory_files] Write failed for {file_path.name}, cleaning up temp file: {e}")
            Path(temp_path).unlink(missing_ok=True)
            raise e

    except PermissionError:
        logger.warning(f"[memory_files] Permission denied writing {file_path.name}")
        return {"success": False, "error": f"Permission denied writing {file_path.name}"}

    except Exception as e:
        logger.warning(f"[memory_files] Failed to write {file_path.name}: {e}")
        return {"success": False, "error": f"Failed to write {file_path.name}: {e}"}


def read_memory_file_data(file_path: Path) -> Optional[Dict[str, Any]]:
    """Read memory file and return data directly, or None on any error."""
    result = read_memory_file(file_path)
    if result["success"]:
        return result.get("data")
    return None


def write_memory_file_simple(file_path: Path, data: Dict[str, Any]) -> bool:
    """Write memory file and return a success boolean."""
    result = write_memory_file(file_path, data)
    return result["success"]


def validate_memory_file_structure(data: Dict[str, Any]) -> tuple[bool, str]:
    """Validate memory file has document_metadata and its expected fields: (is_valid, error)."""
    if not isinstance(data, dict):
        return False, "Data is not a dictionary"

    if "document_metadata" not in data:
        return False, "Missing 'document_metadata' field"

    metadata = data["document_metadata"]

    if not isinstance(metadata, dict):
        return False, "'document_metadata' is not a dictionary"

    expected = ["document_type", "document_name", "version"]
    missing = [field for field in expected if field not in metadata]

    if missing:
        return False, f"Missing metadata fields: {', '.join(missing)}"

    return True, ""


if __name__ == "__main__":
    import sys as _sys

    print("\n=== MEMORY FILE I/O HANDLER - Safe Operations Test ===\n")

    if len(_sys.argv) > 1:
        test_file = Path(_sys.argv[1])
    else:
        print("Usage: drone @memory (via handler memory_files.py)")
        print("No file specified, exiting.")
        _sys.exit(0)

    if test_file.exists():
        print(f"[TEST] Reading {test_file.name}...")
        result = read_memory_file(test_file)

        if result["success"]:
            file_data = result["data"]
            print("+ Read successful")
            print(f"   Document type: {file_data.get('document_metadata', {}).get('document_type')}")
            entry_counts = {k: len(v) for k, v in file_data.items() if isinstance(v, list)}
            print(f"   Entries: {entry_counts}")

            valid, error = validate_memory_file_structure(file_data)
            if valid:
                print("+ Structure validation passed")
            else:
                print(f"- Structure validation failed: {error}")
        else:
            print(f"- Read failed: {result['error']}")
    else:
        print(f"\n[TEST] Test file not found: {test_file}")

    print()
