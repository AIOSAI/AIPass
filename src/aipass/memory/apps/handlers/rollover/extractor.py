# =================== AIPass ====================
# Name: extractor.py
# Description: Memory Extraction Handler
# Version: 0.4.0
# Created: 2025-11-16
# Modified: 2026-03-06
# =============================================

"""
Memory Extraction Handler

Surgically extracts oldest items from memory files during rollover.
Understands real JSON structure (sessions, observations, key_learnings arrays).

Purpose:
    v2 entry-count based extraction: When entry counts exceed limits
    (sessions, key_learnings, observations), extract oldest entries by count.
    Limits are read from config per_branch with defaults fallback.

Strategy:
    - v2: entry-count based extraction (sessions + key_learnings + observations arrays)
    - Extract oldest items (FIFO)
    - Update document_metadata.status
    - No line-count fallbacks — errors over silent fallbacks
"""

import shutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

# Handler imports (relative within package)
from aipass.memory.apps.handlers.json import json_handler, config_loader
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple
from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()

# No module imports (handler independence)


# =============================================================================
# BACKUP OPERATIONS
# =============================================================================


def create_rollover_backup(file_path: Path) -> Dict[str, Any]:
    """
    Create backup before rollover (safety net)

    Creates backup in branch's .backup/ directory with timestamp.
    Only keeps ONE backup - overwrites previous rollover backup.

    Args:
        file_path: Path to memory file to backup

    Returns:
        Dict with backup path and success status
    """
    try:
        # Create .backup directory in branch root
        # For .trinity/ files, go up to branch root; otherwise use file's parent
        if file_path.parent.name == ".trinity":
            backup_dir = file_path.parent.parent / ".backup"
        else:
            backup_dir = file_path.parent / ".backup"
        backup_dir.mkdir(exist_ok=True)

        # Backup filename: rollover_backup.json (always overwrites)
        backup_name = f"rollover_backup_{file_path.name}"
        backup_path = backup_dir / backup_name

        # Copy file
        shutil.copy2(file_path, backup_path)

        return {"success": True, "backup_path": str(backup_path), "message": f"Backup created: {backup_path.name}"}

    except Exception as e:
        logger.error(f"[extractor] Backup failed for {file_path}: {e}")
        return {"success": False, "error": f"Backup failed: {e}"}


def restore_from_backup(file_path: Path) -> Dict[str, Any]:
    """
    Restore file from rollover backup

    Called when rollover fails to restore original state.

    Args:
        file_path: Path to memory file to restore

    Returns:
        Dict with restore status
    """
    try:
        # Match backup location from create_rollover_backup
        if file_path.parent.name == ".trinity":
            backup_dir = file_path.parent.parent / ".backup"
        else:
            backup_dir = file_path.parent / ".backup"
        backup_name = f"rollover_backup_{file_path.name}"
        backup_path = backup_dir / backup_name

        if not backup_path.exists():
            return {"success": False, "error": "No backup found to restore from"}

        # Restore from backup
        shutil.copy2(backup_path, file_path)

        return {"success": True, "message": f"Restored from backup: {backup_path.name}"}

    except Exception as e:
        logger.error(f"[extractor] Restore from backup failed for {file_path}: {e}")
        return {"success": False, "error": f"Restore failed: {e}"}


# =============================================================================
# FILE OPERATIONS
# =============================================================================


def _read_memory_file(file_path: Path) -> Dict[str, Any] | None:
    """Read memory JSON file using memory_files handler."""
    return read_memory_file_data(file_path)


def _write_memory_file(file_path: Path, data: Dict[str, Any]) -> None:
    """Write memory JSON file using json_handler"""
    write_memory_file_simple(file_path, data)


def _count_file_lines(file_path: Path) -> int:
    """Count physical lines in file"""
    with open(file_path, "r", encoding="utf-8") as f:
        return len(f.readlines())


# =============================================================================
# PATH HELPERS
# =============================================================================


def _derive_branch_and_type(file_path: Path) -> tuple[str, str]:
    """
    Derive branch name and memory type from file path.

    Handles both naming conventions:
    - .trinity/local.json → branch from parent.parent.name, type from stem
    - BRANCH.type.json (legacy) → parsed from stem

    Returns:
        Tuple of (branch_name, memory_type) e.g. ("DEVPULSE", "local")
    """
    if file_path.parent.name == ".trinity":
        branch_name = file_path.parent.parent.name.upper()
        memory_type = file_path.stem  # "local" or "observations"
    else:
        parts = file_path.stem.split(".")
        branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
        memory_type = parts[1] if len(parts) > 1 else "unknown"
    return branch_name, memory_type


# =============================================================================
# EXTRACTION CALCULATION
# =============================================================================


# =============================================================================
# V2 EXTRACTION (ENTRY-COUNT BASED)
# =============================================================================


def _is_misplaced_entry(entry: Any, head_number: int | None) -> bool:
    """
    An entry in the tail (about to be archived as "oldest") that is dated
    today or numbered above the array's head is not oldest history — it's a
    fresh write landed at the wrong end (post-compact convention loss).
    """
    if not isinstance(entry, dict):
        return False
    if entry.get("date") == datetime.now().strftime("%Y-%m-%d"):
        return True
    number = entry.get("number")
    if isinstance(number, int) and isinstance(head_number, int) and number > head_number:
        return True
    return False


def _ensure_newest_first(entries: list, array_name: str, branch_key: str) -> tuple[list, bool]:
    """
    Guarantee an array is newest-first before the tail is treated as oldest.

    Rollover's whole contract is "the tail is the oldest history". A branch
    storing its entries oldest-first inverts that, so the tail is the NEWEST
    entry and rollover eats fresh memories one run at a time. The safety valve
    alone cannot catch this: once a correctly-prepended entry sits at the head,
    the misordered legacy block below it looks perfectly plausible.

    Returns (entries_newest_first, repaired) — `repaired` is True when the
    stored order was wrong and had to be corrected.
    """
    if not isinstance(entries, list) or len(entries) < 2:
        return entries, False
    if not all(isinstance(e, dict) and isinstance(e.get("number"), int) for e in entries):
        return entries, False

    ordered = sorted(entries, key=lambda e: e["number"], reverse=True)
    if ordered == entries:
        return entries, False

    logger.warning(
        f"[extractor] {branch_key}/{array_name}: stored order was NOT newest-first — "
        f"re-sorted by number before archiving (head #{entries[0].get('number')} -> "
        f"#{ordered[0].get('number')}). Rollover would otherwise have archived the newest "
        f"entries as oldest history."
    )
    return ordered, True


def _extract_tail_excess(
    entries: list, limit: int | None, head_number: int | None, array_name: str, branch_key: str
) -> list:
    """
    Select the oldest entries beyond `limit` for archival, holding back any
    that look like misplaced fresh writes (safety valve).

    Returns the list of entries safe to archive; may be empty.
    """
    if limit is None or not isinstance(entries, list) or len(entries) < limit:
        return []
    excess = max(len(entries) - limit, 1)
    candidate_tail = entries[-excess:]  # oldest from end

    archivable = []
    for entry in candidate_tail:
        if _is_misplaced_entry(entry, head_number):
            logger.warning(
                f"[extractor] {branch_key}/{array_name}: refusing to archive misplaced entry "
                f"(dated today or numbered above head #{head_number}) — treating as a fresh "
                f"write, not oldest history: {entry}"
            )
        else:
            archivable.append(entry)
    return archivable


def _extract_items_v2(file_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract items from v2 format file (entry-count based).

    Handles sessions, key_learnings, and observations (arrays, newest-first, oldest at end).
    Trims to max_sessions / max_key_learnings limits defined in document_metadata.

    Args:
        file_path: Path to memory JSON file
        data: Already-parsed JSON data

    Returns:
        Dict with extracted items and metadata
    """
    old_lines = _count_file_lines(file_path)

    # Read limits from config per_branch instead of file metadata
    if file_path.parent.name == ".trinity":
        branch_key = file_path.parents[1].name.lower()
        file_type = file_path.stem  # "local" or "observations"
    else:
        branch_key = file_path.parent.name.lower()
        file_type = file_path.stem.split(".")[-1]

    cfg = config_loader.section("rollover")
    file_limits = cfg.get("per_branch", {}).get(branch_key, {}).get(file_type, {})

    all_extracted = []

    # Extract from sessions array (newest first, oldest at end). AUTO-COMPACT
    # SNAPSHOT entries (status == "auto-compact") get their own small cap and
    # never count against the regular session budget.
    order_repaired = False

    sessions = data.get("sessions", [])
    if isinstance(sessions, list) and sessions:
        sessions, repaired = _ensure_newest_first(sessions, "sessions", branch_key)
        if repaired:
            data["sessions"] = sessions
            order_repaired = True
        session_limits = file_limits.get("sessions", {})
        head_number = sessions[0].get("number") if isinstance(sessions[0], dict) else None

        auto_compact_cap = session_limits.get("auto_compact_cap")
        if auto_compact_cap is not None:
            auto_entries = [e for e in sessions if isinstance(e, dict) and e.get("status") == "auto-compact"]
            archived_auto = _extract_tail_excess(
                auto_entries, auto_compact_cap, head_number, "sessions(auto-compact)", branch_key
            )
            if archived_auto:
                archived_ids = {id(e) for e in archived_auto}
                sessions = [e for e in sessions if id(e) not in archived_ids]
                all_extracted.extend(archived_auto)

        max_sessions = session_limits.get("count")
        if max_sessions is not None:
            regular_entries = [e for e in sessions if not (isinstance(e, dict) and e.get("status") == "auto-compact")]
            archived_regular = _extract_tail_excess(regular_entries, max_sessions, head_number, "sessions", branch_key)
            if archived_regular:
                archived_ids = {id(e) for e in archived_regular}
                sessions = [e for e in sessions if id(e) not in archived_ids]
                all_extracted.extend(archived_regular)

        data["sessions"] = sessions

    # Extract from key_learnings list (sorted newest-first; oldest at end)
    key_learnings = data.get("key_learnings", [])
    if isinstance(key_learnings, list) and key_learnings:
        key_learnings, repaired = _ensure_newest_first(key_learnings, "key_learnings", branch_key)
        if repaired:
            data["key_learnings"] = key_learnings
            order_repaired = True
    max_key_learnings = file_limits.get("key_learnings", {}).get("count")
    if max_key_learnings is not None and isinstance(key_learnings, list) and key_learnings:
        kl_head_number = key_learnings[0].get("number") if isinstance(key_learnings[0], dict) else None
        archived_kl = _extract_tail_excess(
            key_learnings, max_key_learnings, kl_head_number, "key_learnings", branch_key
        )
        if archived_kl:
            archived_ids = {id(e) for e in archived_kl}
            data["key_learnings"] = [e for e in key_learnings if id(e) not in archived_ids]
            all_extracted.extend(archived_kl)

    # Extract from observations array (if v2 observations file)
    observations = data.get("observations", [])
    if isinstance(observations, list) and observations:
        observations, repaired = _ensure_newest_first(observations, "observations", branch_key)
        if repaired:
            data["observations"] = observations
            order_repaired = True
    max_observations = file_limits.get("observations", {}).get("count")
    if max_observations is not None and isinstance(observations, list) and observations:
        obs_head_number = observations[0].get("number") if isinstance(observations[0], dict) else None
        archived_obs = _extract_tail_excess(observations, max_observations, obs_head_number, "observations", branch_key)
        if archived_obs:
            archived_ids = {id(e) for e in archived_obs}
            data["observations"] = [e for e in observations if id(e) not in archived_ids]
            all_extracted.extend(archived_obs)

    if not all_extracted:
        # An order repair with nothing to archive must still be persisted, or the
        # file stays misordered and the next run re-detects the same fault.
        if order_repaired:
            try:
                _write_memory_file(file_path, data)
                logger.info(f"[extractor] {branch_key}: persisted newest-first order repair (nothing archived)")
            except Exception as e:
                logger.error(f"[extractor] Failed to persist order repair: {e}")
                return {"success": False, "error": f"Failed to write file: {e}"}
        return {"success": True, "skipped": True, "message": "No entries exceed v2 limits"}

    # Update metadata
    _update_metadata_after_extraction(data)

    # Write back
    try:
        _write_memory_file(file_path, data)
        new_lines = _count_file_lines(file_path)
    except Exception as e:
        logger.error(f"[extractor] Failed to write file after v2 extraction: {e}")
        return {"success": False, "error": f"Failed to write file: {e}"}

    # Derive branch and type from path
    # .trinity/local.json → branch = parent.parent.name, type = stem
    branch_name, memory_type = _derive_branch_and_type(file_path)

    return {
        "success": True,
        "file": str(file_path),
        "branch": branch_name,
        "type": memory_type,
        "array_field": "v2_mixed",
        "extracted": all_extracted,
        "extracted_count": len(all_extracted),
        "remaining_count": 0,
        "old_lines": old_lines,
        "new_lines": new_lines,
    }


# =============================================================================
# EXTRACTION OPERATIONS
# =============================================================================


def extract_items(file_path: Path, percentage: int | None = None) -> Dict[str, Any]:
    """
    Extract items from memory file (WITH BACKUP SAFETY)

    Now includes automatic backup before modification.
    File is modified immediately, but backup exists for recovery.

    Args:
        file_path: Path to memory JSON file
        percentage: Percentage of items to extract (auto-calculated if None)

    Returns:
        Dict with extracted items and metadata
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    # Read file
    try:
        data = _read_memory_file(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse memory file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[extractor] Failed to read file {file_path}: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    # v2: entry-count based extraction — triggered when config has per_branch counts
    if file_path.parent.name == ".trinity":
        _ext_branch = file_path.parents[1].name.lower()
        _ext_ftype = file_path.stem
    else:
        _ext_branch = file_path.parent.name.lower()
        _ext_ftype = file_path.stem.split(".")[-1]
    _ext_cfg = config_loader.section("rollover")
    _ext_file_limits = _ext_cfg.get("per_branch", {}).get(_ext_branch, {}).get(_ext_ftype, {})
    if not _ext_file_limits:
        # Also check defaults fallback
        _ext_file_limits = _ext_cfg.get("defaults", {}).get(_ext_ftype, {})

    if _ext_file_limits:
        return _extract_items_v2(file_path, data)

    # No v2 limits found — fail loud, never fall back to v1 line-count
    logger.warning(
        f"[extractor] NO V2 LIMITS for branch={_ext_branch} file_type={_ext_ftype} "
        f"— cannot extract without config. Check per_branch and defaults in memory.config.json"
    )
    json_handler.log_operation(
        "extract_items_no_limits",
        {"branch": _ext_branch, "file_type": _ext_ftype, "error": "no v2 limits configured"},
    )
    return {
        "success": False,
        "error": f"No v2 extraction limits configured for {_ext_branch}/{_ext_ftype}",
    }


# =============================================================================
# METADATA OPERATIONS
# =============================================================================


def _update_metadata_after_extraction(data: Dict[str, Any]) -> None:
    """
    Update document_metadata after extraction.

    Updates:
    - status.last_health_check

    Args:
        data: JSON data dict (modified in place)
    """
    # Ensure metadata structure
    if "document_metadata" not in data:
        data["document_metadata"] = {}

    metadata = data["document_metadata"]

    # Update status
    if "status" not in metadata:
        metadata["status"] = {}

    metadata["status"]["last_health_check"] = datetime.now().strftime("%Y-%m-%d")


# =============================================================================
# VECTORIZATION PREPARATION
# =============================================================================


def extract_with_metadata(file_path: Path, percentage: int | None = None) -> Dict[str, Any]:
    """
    Extract items with enriched metadata for vectorization

    Same as extract_items but adds metadata needed for vector storage.

    Args:
        file_path: Path to memory JSON file
        percentage: Percentage of items to extract (auto-calculated if None)

    Returns:
        Dict with extracted items + vectorization metadata
    """
    # Do standard extraction
    result = extract_items(file_path, percentage)

    if not result["success"]:
        return result

    if result.get("skipped"):
        return {
            "success": True,
            "skipped": True,
            "message": result.get("message", "Extraction skipped"),
            "entries": [],
            "count": 0,
            "branch": result.get("branch"),
            "type": result.get("type"),
        }

    # Enrich extracted items with metadata
    extracted = result.get("extracted", [])
    branch = result.get("branch")
    memory_type = result.get("type")
    array_field = result.get("array_field")

    extraction_timestamp = datetime.now().isoformat()

    enriched = []
    for item in extracted:
        enriched_item = {
            **item,  # Preserve original item data
            "_metadata": {
                "branch": branch,
                "type": memory_type,
                "array_field": array_field,
                "extracted_at": extraction_timestamp,
                "source_file": file_path.name,
            },
        }
        enriched.append(enriched_item)

    # Return enriched version
    return {
        "success": True,
        "file": str(file_path),
        "branch": branch,
        "type": memory_type,
        "array_field": array_field,
        "entries": enriched,
        "count": len(enriched),
        "old_lines": result.get("old_lines"),
        "new_lines": result.get("new_lines"),
    }
