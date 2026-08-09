# =================== AIPass ====================
# Name: memory_files.py
# Description: Memory File Safe I/O Handler
# Version: 1.2.0
# Created: 2026-03-17
# Modified: 2026-08-08
# =============================================

"""
Memory File I/O Handler

Safe read/write operations for branch memory files (*.local.json, *.observations.json).
Handles atomic writes and proper error handling for .trinity/ file management.

Purpose:
    Prevent corruption of critical memory files during read/write operations.
    All memory file access should use these functions instead of direct json.load/dump.

Features:
    - Atomic writes (temp file + rename)
    - Safe error handling
    - Metadata helpers
    - Preserves formatting (indent=2, ensure_ascii=False)

Usage:
    from aipass.memory.apps.handlers.json.memory_files import read_memory_file, write_memory_file
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader
from aipass.memory.apps.handlers.json.entry_limits import load_entry_limits, changed_entries

logger = get_system_logger()

# Resolve paths relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_DIR = _MEMORY_ROOT / "config"
_TEMPLATES_DIR = _MEMORY_ROOT / "apps" / "json_templates"

# No service imports - handlers are pure workers (3-tier architecture)
# No module imports (handler independence)

# Files tracked by entry-limits validation
_TRACKED_TRINITY_FILES = {"local.json", "observations.json"}


# =============================================================================
# ENTRY-LIMITS VALIDATION (rollover-safe)
# =============================================================================


def _validate_entry_limits(
    file_path: Path,
    data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Check entry limits for a .trinity/ write and return a rejection or None.

    Only validates files inside a ``.trinity/`` directory whose name is
    in :data:`_TRACKED_TRINITY_FILES`.  For all other paths this function
    returns ``None`` immediately (no validation).

    Unchanged entries (same text as on disk) are intentionally skipped so
    that rollover and other maintenance writes are never blocked by
    legacy over-limit entries.

    Args:
        file_path: Target path for the write.
        data: The dict about to be written.

    Returns:
        ``None`` when the write should proceed normally.
        A ``{"success": False, "error": ...}`` dict when enforce mode is
        on and new/changed entries exceed their caps.
    """
    # --- Gate: only tracked .trinity files ------------------------------------
    if file_path.parent.name != ".trinity":
        return None
    if file_path.name not in _TRACKED_TRINITY_FILES:
        return None

    branch = file_path.parent.parent.name
    limits = load_entry_limits(branch)

    if not limits.get("enabled", True):
        return None

    # Filter limits to entry_types that belong to THIS file
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

    # Read current on-disk content (before)
    before: Dict[str, Any] = {}
    if file_path.exists():
        try:
            before = json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"[entry_limits] Could not parse {file_path.name} for diff: {exc}")
            before = {}  # Unparseable — treat as empty (all entries "new")

    over = changed_entries(before, data, filtered_limits)
    if not over:
        return None

    # --- Violations found -----------------------------------------------------
    enforce = limits.get("enforce", False)

    if not enforce:
        for violation in over:
            logger.warning(
                f"[entry_limits] WARN {branch} {file_path.name} "
                f"{violation['container']}[{violation['key']}] "
                f"{violation['length']}/{violation['cap']} "
                f"(+{violation['over_by']} over)"
            )
        return None  # Write through in warn mode

    # Enforce mode — block the write
    details = "; ".join(f"{v['container']}[{v['key']}] {v['length']}/{v['cap']} (+{v['over_by']} over)" for v in over)
    return {"success": False, "error": f"Entry limit exceeded: {details}"}


def _is_auto_compact(entry: Any) -> bool:
    """True for auto-compact snapshot entries.

    Must match rollover/extractor.py exactly — a guard that classified
    entries differently from the extractor is how the false ENTRY COUNT
    spam started in the first place.
    """
    return isinstance(entry, dict) and entry.get("status") == "auto-compact"


def _warn_entry_count(branch: str, file_name: str, label: str, count: int, cap: int) -> None:
    """Emit one soft-guard warning line for an over-cap section."""
    logger.warning(
        f"[memory_files] ENTRY COUNT: {branch} {file_name} "
        f"{label} has {count}/{cap} entries "
        f"(+{count - cap} over rollover limit)"
    )


def _check_session_counts(branch: str, file_name: str, entries: list, section_cfg: Dict[str, Any]) -> None:
    """Warn on the sessions section, budgeting snapshots separately.

    Auto-compact snapshots carry their own small cap in the extractor and
    never count against the regular session budget.  Checking the combined
    array against the regular cap made this guard permanently unsatisfiable:
    rollover correctly archived nothing while the warning fired on every
    .trinity write, fleet-wide.
    """
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
    """Soft guard: warn when list entry counts exceed rollover limits.

    Does NOT block writes — only logs warnings so over-limit growth
    between rollovers is visible in prax logs.
    """
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


# =============================================================================
# CORE READ/WRITE OPERATIONS
# =============================================================================


def read_memory_file(file_path: Path) -> Dict[str, Any]:
    """
    Safe read of memory JSON file

    Handles file not found, corrupt JSON, and other read errors gracefully.

    Args:
        file_path: Path to memory JSON file

    Returns:
        Dict with success status and data: {'success': True, 'data': {...}} or {'success': False, 'error': '...'}

    Example:
        result = read_memory_file(Path("path/to/BRANCH.local.json"))
        if result['success']:
            data = result['data']
            sessions = data.get('sessions', [])
    """
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
    """
    Atomic write of memory JSON file

    Uses temp file + rename strategy to prevent corruption on write failures.
    Preserves formatting (indent=2, ensure_ascii=False) for readability.

    Args:
        file_path: Path to memory JSON file
        data: JSON data to write (must be dict)

    Returns:
        Dict with success status: {'success': True, 'file': '...'} or {'success': False, 'error': '...'}

    Example:
        result = read_memory_file(path)
        if result['success']:
            data = result['data']
            data['sessions'].append(new_session)
            write_result = write_memory_file(path, data)

    Safety:
        - Writes to temp file first
        - Only renames if write succeeds
        - Original file unchanged if write fails
    """
    if not isinstance(data, dict):
        return {"success": False, "error": f"Data must be dict, got {type(data).__name__}"}

    # --- Entry-limits validation (rollover-safe) ------------------------------
    # Only validate .trinity/ files that are tracked (local.json, observations.json).
    # Unchanged legacy over-limit entries pass untouched so rollover is never blocked.
    try:
        rejection = _validate_entry_limits(file_path, data)
        if rejection is not None:
            return rejection
    except Exception as exc:
        logger.warning(f"[memory_files] Entry-limits validation error (writing anyway): {exc}")

    # --- Soft entry-count guard (warn-only, never blocks) --------------------
    try:
        _check_entry_counts(file_path, data)
    except Exception as exc:
        logger.warning(f"[memory_files] Entry-count check error (writing anyway): {exc}")

    try:
        # Create temp file in same directory (for atomic rename)
        temp_fd, temp_path = tempfile.mkstemp(dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp")

        try:
            # Write to temp file
            with open(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")  # Add final newline

            # Atomic replace (os.replace overwrites on both Linux and Windows)
            os.replace(temp_path, file_path)

            json_handler.log_operation("write_memory_file", {"file": file_path.name, "success": True})

            return {"success": True, "file": str(file_path)}

        except Exception as e:
            # Clean up temp file on failure
            logger.error(f"[memory_files] Write failed for {file_path.name}, cleaning up temp file: {e}")
            Path(temp_path).unlink(missing_ok=True)
            raise e

    except PermissionError:
        logger.warning(f"[memory_files] Permission denied writing {file_path.name}")
        return {"success": False, "error": f"Permission denied writing {file_path.name}"}

    except Exception as e:
        logger.warning(f"[memory_files] Failed to write {file_path.name}: {e}")
        return {"success": False, "error": f"Failed to write {file_path.name}: {e}"}


# =============================================================================
# METADATA HELPERS
# =============================================================================


def update_metadata(
    file_path: Path,
    **updates: Any,
) -> Dict[str, Any]:
    """
    Update document_metadata.status fields

    Convenient helper for updating metadata without manual read-modify-write.
    Only updates document_metadata.status fields, preserves rest of file.

    Args:
        file_path: Path to memory JSON file
        **updates: Key-value pairs to update in status section

    Returns:
        Dict with success status: {'success': True} or {'success': False, 'error': '...'}

    Example:
        # Update health and line count
        update_metadata(
            path,
            health="healthy",
            current_lines=450,
            last_health_check="2025-11-16"
        )

    Safety:
        - Uses atomic write
        - Creates metadata structure if missing
        - Preserves all other data
    """
    # Read current data
    read_result = read_memory_file(file_path)
    if not read_result["success"]:
        return read_result

    data = read_result["data"]

    # Ensure metadata structure exists
    if "document_metadata" not in data:
        data["document_metadata"] = {}

    if "status" not in data["document_metadata"]:
        data["document_metadata"]["status"] = {}

    # Apply updates
    status = data["document_metadata"]["status"]
    for key, value in updates.items():
        status[key] = value

    # Write back
    write_result = write_memory_file(file_path, data)

    return write_result


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def read_memory_file_data(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Read memory file and return data directly (no dict wrapper)

    Convenience function for simple reads where you just need the data.
    Returns None on any error.

    Args:
        file_path: Path to memory JSON file

    Returns:
        Parsed JSON data dict, or None on error

    Example:
        data = read_memory_file_data(path)
        if data:
            sessions = data.get('sessions', [])
    """
    result = read_memory_file(file_path)
    if result["success"]:
        return result.get("data")
    return None


def write_memory_file_simple(file_path: Path, data: Dict[str, Any]) -> bool:
    """
    Write memory file and return simple success/failure boolean

    Convenience function for simple writes where you just need success flag.

    Args:
        file_path: Path to memory JSON file
        data: JSON data to write

    Returns:
        True if successful, False otherwise

    Example:
        data['sessions'].append(new_session)
        if write_memory_file_simple(path, data):
            print("Success!")
    """
    result = write_memory_file(file_path, data)
    return result["success"]


# =============================================================================
# VALIDATION HELPERS
# =============================================================================


def validate_memory_file_structure(data: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate memory file has required structure

    Checks for document_metadata presence and basic structure.

    Args:
        data: Parsed JSON data

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        data = read_memory_file_data(path)
        valid, error = validate_memory_file_structure(data)
        if not valid:
            logger.warning(f"Invalid structure: {error}")
    """
    if not isinstance(data, dict):
        return False, "Data is not a dictionary"

    if "document_metadata" not in data:
        return False, "Missing 'document_metadata' field"

    metadata = data["document_metadata"]

    if not isinstance(metadata, dict):
        return False, "'document_metadata' is not a dictionary"

    # Check for expected fields
    expected = ["document_type", "document_name", "version"]
    missing = [field for field in expected if field not in metadata]

    if missing:
        return False, f"Missing metadata fields: {', '.join(missing)}"

    return True, ""


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    import sys as _sys

    print("\n=== MEMORY FILE I/O HANDLER - Safe Operations Test ===\n")

    # Test with a file passed as argument, or show usage
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
            file_status = file_data.get("document_metadata", {}).get("status", {}).get("health")
            print(f"   Status: {file_status}")

            # Validate structure
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
