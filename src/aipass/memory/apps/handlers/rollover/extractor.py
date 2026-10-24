# =================== AIPass ====================
# Name: extractor.py
# Description: Memory Extraction Handler
# Version: 0.8.0
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

"""
Memory Extraction Handler
"""

from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

# Handler imports (relative within package)
from aipass.memory.apps.handlers.json import json_handler, config_loader
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple
from aipass.memory.apps.handlers.monitor.detector import _count_file_lines, file_limits, undrainable_in
from aipass.prax.apps.modules.logger import get_system_logger

logger = get_system_logger()


def _read_memory_file(file_path: Path) -> Dict[str, Any] | None:
    """Read memory JSON file using memory_files handler."""
    return read_memory_file_data(file_path)


def _write_memory_file(file_path: Path, data: Dict[str, Any]) -> None:
    """Write memory JSON file, RAISING when the write is refused.

    `write_memory_file_simple` returns False instead of raising; swallowing it lets the
    archive store entries the file never gave up. The OSError makes ``commit_trimmed`` a refusal.
    """
    if not write_memory_file_simple(file_path, data):
        raise OSError(
            f"write refused for {file_path} — the memory-file writer returned False. "
            f"Rollover authors no text, so a cap refusal here would be a bug in the "
            f"gate, not drift in the file; see prax for the writer's own reason"
        )


def _derive_branch_and_type(file_path: Path) -> tuple[str, str]:
    """Derive (BRANCH, type) from .trinity/<type>.json or legacy BRANCH.type.json."""
    if file_path.parent.name == ".trinity":
        branch_name = file_path.parent.parent.name.upper()
        memory_type = file_path.stem  # "local" or "observations"
    else:
        parts = file_path.stem.split(".")
        branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
        memory_type = parts[1] if len(parts) > 1 else "unknown"
    return branch_name, memory_type


def _is_misplaced_entry(
    entry: Any, head_number: int | None, date_guard: bool = True, head_date: str | None = None
) -> bool:
    """A tail entry numbered above the head, or dated today, is a fresh write at the wrong end.

    `date_guard=False` drops the date half when the number can decide. "Dated today" is
    only evidence when the head is not also dated today; with no usable number the date
    rule always applies, and an unknown `head_date` reads as "not today".
    """
    if not isinstance(entry, dict):
        return False

    number = entry.get("number")
    ordering_says_correct_end = False
    if isinstance(number, int) and isinstance(head_number, int):
        if number > head_number:
            return True
        if not date_guard:
            return False
        ordering_says_correct_end = number < head_number

    if entry.get("date") != datetime.now().strftime("%Y-%m-%d"):
        return False

    return not (ordering_says_correct_end and head_date == datetime.now().strftime("%Y-%m-%d"))


def _ensure_newest_first(entries: list, array_name: str, branch_key: str) -> tuple[list, bool]:
    """Guarantee an array is newest-first before the tail is treated as oldest; returns (entries, repaired).

    The safety valve cannot catch an oldest-first legacy block once a correct entry sits at the head.
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
    entries: list,
    limit: int | None,
    head_number: int | None,
    array_name: str,
    branch_key: str,
    date_guard: bool = True,
    head_date: str | None = None,
) -> list:
    """Select the oldest entries beyond `limit` for archival, holding back misplaced fresh writes."""
    if limit is None or not isinstance(entries, list) or len(entries) <= limit:
        return []
    # keep-N keeps N. Moves with monitor/detector.py `_should_rollover`, or the file re-fires forever.
    excess = len(entries) - limit
    candidate_tail = entries[-excess:]  # oldest from end

    reason = "numbered above head" if not date_guard else "dated today or numbered above head"
    archivable = []
    refused: list = []
    for entry in candidate_tail:
        if _is_misplaced_entry(entry, head_number, date_guard=date_guard, head_date=head_date):
            refused.append(entry)
            logger.debug(
                f"[extractor] {branch_key}/{array_name}: refused misplaced entry ({reason} #{head_number}): {entry}"
            )
        else:
            archivable.append(entry)

    # One warning per array per run: a warning per refusal floods the log at scale.
    if refused:
        drained = len(archivable)
        summary = (
            f"[extractor] {branch_key}/{array_name}: held back {len(refused)} of "
            f"{len(candidate_tail)} candidates as misplaced ({reason} #{head_number}) "
            f"— treating them as fresh writes, not oldest history"
        )
        if drained:
            logger.warning(summary)
        else:
            logger.warning(
                f"{summary}. NOTHING DRAINED — this file is over its limit and no "
                f"candidate is archivable, so rollover will re-fire and refuse the same "
                f"entries every run. Newest entries are at the tail: the array is not "
                f"newest-first, or its entries carry no usable 'number'."
            )
    return archivable


def _extract_items_v2(file_path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract items from v2 format file (entry-count based)."""
    old_lines = _count_file_lines(file_path)
    branch_key, _file_type, limits = file_limits(config_loader.section("rollover"), file_path)

    all_extracted = []

    # auto-compact snapshots get their own cap and never count against the regular session budget.
    order_repaired = False

    sessions = data.get("sessions", [])
    if isinstance(sessions, list) and sessions:
        sessions, repaired = _ensure_newest_first(sessions, "sessions", branch_key)
        if repaired:
            data["sessions"] = sessions
            order_repaired = True
        session_limits = limits.get("sessions", {})
        # Each lane takes its head from its own entries: a shared head lets a snapshot judge regulars.

        auto_compact_cap = session_limits.get("auto_compact_cap")
        if auto_compact_cap is not None:
            auto_entries = [e for e in sessions if isinstance(e, dict) and e.get("status") == "auto-compact"]
            # Snapshots are written many times a day, so date_guard=False: only order says which is oldest.
            auto_head = auto_entries[0] if auto_entries and isinstance(auto_entries[0], dict) else {}
            archived_auto = _extract_tail_excess(
                auto_entries,
                auto_compact_cap,
                auto_head.get("number"),
                "sessions(auto-compact)",
                branch_key,
                date_guard=False,
                head_date=auto_head.get("date"),
            )
            if archived_auto:
                archived_ids = {id(e) for e in archived_auto}
                sessions = [e for e in sessions if id(e) not in archived_ids]
                all_extracted.extend(archived_auto)

        max_sessions = session_limits.get("count")
        if max_sessions is not None:
            regular_entries = [e for e in sessions if not (isinstance(e, dict) and e.get("status") == "auto-compact")]
            regular_head = regular_entries[0] if regular_entries and isinstance(regular_entries[0], dict) else {}
            archived_regular = _extract_tail_excess(
                regular_entries,
                max_sessions,
                regular_head.get("number"),
                "sessions",
                branch_key,
                head_date=regular_head.get("date"),
            )
            if archived_regular:
                archived_ids = {id(e) for e in archived_regular}
                sessions = [e for e in sessions if id(e) not in archived_ids]
                all_extracted.extend(archived_regular)

        data["sessions"] = sessions

    key_learnings = data.get("key_learnings", [])
    if isinstance(key_learnings, list) and key_learnings:
        key_learnings, repaired = _ensure_newest_first(key_learnings, "key_learnings", branch_key)
        if repaired:
            data["key_learnings"] = key_learnings
            order_repaired = True
    max_key_learnings = limits.get("key_learnings", {}).get("count")
    if max_key_learnings is not None and isinstance(key_learnings, list) and key_learnings:
        kl_head = key_learnings[0] if isinstance(key_learnings[0], dict) else {}
        archived_kl = _extract_tail_excess(
            key_learnings,
            max_key_learnings,
            kl_head.get("number"),
            "key_learnings",
            branch_key,
            head_date=kl_head.get("date"),
        )
        if archived_kl:
            archived_ids = {id(e) for e in archived_kl}
            data["key_learnings"] = [e for e in key_learnings if id(e) not in archived_ids]
            all_extracted.extend(archived_kl)

    observations = data.get("observations", [])
    if isinstance(observations, list) and observations:
        observations, repaired = _ensure_newest_first(observations, "observations", branch_key)
        if repaired:
            data["observations"] = observations
            order_repaired = True
    max_observations = limits.get("observations", {}).get("count")
    if max_observations is not None and isinstance(observations, list) and observations:
        obs_head = observations[0] if isinstance(observations[0], dict) else {}
        archived_obs = _extract_tail_excess(
            observations,
            max_observations,
            obs_head.get("number"),
            "observations",
            branch_key,
            head_date=obs_head.get("date"),
        )
        if archived_obs:
            archived_ids = {id(e) for e in archived_obs}
            data["observations"] = [e for e in observations if id(e) not in archived_ids]
            all_extracted.extend(archived_obs)

    if not all_extracted:
        # An order repair with nothing to archive must still persist, or the next run re-detects it.
        if order_repaired:
            try:
                _write_memory_file(file_path, data)
                logger.info(f"[extractor] {branch_key}: persisted newest-first order repair (nothing archived)")
            except Exception as e:
                logger.error(f"[extractor] Failed to persist order repair: {e}")
                return {"success": False, "error": f"Failed to write file: {e}"}
        # A dict-held container can be over limit yet undrainable; say so rather than "nothing exceeds".
        undrainable = undrainable_in(data, limits)
        if undrainable:
            return {
                "success": True,
                "skipped": True,
                "message": f"nothing drainable - {'; '.join(undrainable)}; rollover drains lists only",
            }
        return {"success": True, "skipped": True, "message": "No entries exceed v2 limits"}

    # Not written here: the file keeps every entry until the orchestrator has them in the
    # store and calls commit_trimmed. A crash between extraction and storage loses nothing.
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
        "trimmed": data,
    }


def commit_trimmed(file_path: Path, data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Write the trimmed file once its entries are stored; ``new_lines`` on success."""
    if not isinstance(data, dict):
        return {"success": False, "error": "No trimmed data to write"}
    try:
        _write_memory_file(file_path, data)
    except Exception as e:
        logger.error(f"[extractor] Failed to write file after v2 extraction: {e}")
        return {"success": False, "error": f"Failed to write file: {e}"}
    return {"success": True, "new_lines": _count_file_lines(file_path)}


def extract_items(file_path: Path) -> Dict[str, Any]:
    """Extract items from a memory file; the trimmed data is returned, written only by ``commit_trimmed``."""
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        data = _read_memory_file(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse memory file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[extractor] Failed to read file {file_path}: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    _ext_branch, _ext_ftype, _ext_file_limits = file_limits(config_loader.section("rollover"), file_path)

    if _ext_file_limits:
        return _extract_items_v2(file_path, data)

    # Fail loud; never fall back to v1 line-count.
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


def extract_with_metadata(file_path: Path) -> Dict[str, Any]:
    """Extract items with enriched metadata for vectorization"""
    result = extract_items(file_path)

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

    extracted = result.get("extracted", [])
    branch = result.get("branch")
    memory_type = result.get("type")
    array_field = result.get("array_field")

    extraction_timestamp = datetime.now().isoformat()

    enriched = []
    for item in extracted:
        item_metadata = {
            "branch": branch,
            "type": memory_type,
            "array_field": array_field,
            "extracted_at": extraction_timestamp,
            "source_file": file_path.name,
        }

        # Entry identity lets an archived entry be matched and renumbered without text-guessing.
        # ChromaDB metadata takes scalars only.
        if isinstance(item, dict):
            entry_number = item.get("number")
            if isinstance(entry_number, int) and not isinstance(entry_number, bool):
                item_metadata["entry_number"] = entry_number
            entry_date = item.get("date")
            if isinstance(entry_date, str) and entry_date:
                item_metadata["entry_date"] = entry_date

        enriched_item = {
            **item,
            "_metadata": item_metadata,
        }
        enriched.append(enriched_item)

    return {
        "success": True,
        "file": str(file_path),
        "branch": branch,
        "type": memory_type,
        "array_field": array_field,
        "entries": enriched,
        "count": len(enriched),
        "old_lines": result.get("old_lines"),
        "trimmed": result.get("trimmed"),
    }
