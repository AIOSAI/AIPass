# =================== AIPass ====================
# Name: manager.py
# Description: Memory Sections Management Handler
# Version: 1.2.0
# Created: 2026-02-04
# Modified: 2026-03-06
# =============================================

"""
Memory Sections Management Handler

Manages key_learnings and recently_completed sections in branch .local.json files:
- Adds timestamps to entries for age-based pruning
- Enforces max_entries limit (configurable per section)
- Vectorizes dropped entries to memory before removal
- Updates status counts after processing

Purpose:
    Prevent unbounded growth of memory sections while preserving
    historical data in searchable vector storage.

Format:
    key_learnings: list of {number, date, key, value} (v3, newest-first)
                   or dict with "name": "value... [2026-02-04]" (legacy)
    recently_completed: list with "Task description [2026-02-04]"
"""

import sys
import re
import json
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple
from datetime import datetime

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data, write_memory_file_simple

logger = get_system_logger()

# ChromaDB subprocess for vectorization (resolved relative to handler location)
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
CHROMA_SUBPROCESS_SCRIPT = _MEMORY_ROOT / "apps" / "handlers" / "storage" / "chroma_subprocess.py"


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


# Defaults
DEFAULT_MAX_LEARNINGS = 100
DEFAULT_MAX_RECENTLY_COMPLETED = 20
TIMESTAMP_PATTERN = r"\[(\d{4}-\d{2}-\d{2})\]$"


# =============================================================================
# TIMESTAMP OPERATIONS
# =============================================================================


def parse_timestamp(value: str) -> Tuple[str, str | None]:
    """
    Parse timestamp from key_learnings value

    Args:
        value: Learning value string

    Returns:
        Tuple of (value_without_timestamp, timestamp_str or None)

    Example:
        "value... [2026-02-04]" -> ("value...", "2026-02-04")
        "value without timestamp" -> ("value without timestamp", None)
    """
    match = re.search(TIMESTAMP_PATTERN, value.strip())
    if match:
        timestamp = match.group(1)
        clean_value = value[: match.start()].strip()
        return (clean_value, timestamp)
    return (value, None)


def add_timestamp(value: str, date: str | None = None) -> str:
    """
    Add or update timestamp on a key_learnings value

    Args:
        value: Learning value string
        date: Date string (YYYY-MM-DD), defaults to today

    Returns:
        Value with timestamp appended

    Example:
        "my learning" -> "my learning [2026-02-04]"
        "old learning [2025-01-01]" -> "old learning [2026-02-04]"
    """
    clean_value, _ = parse_timestamp(value)
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    return f"{clean_value} [{date}]"


def get_entry_age(value: str) -> int:
    """
    Get age of entry in days

    Args:
        value: Learning value with timestamp

    Returns:
        Age in days, or 999999 if no timestamp (treated as very old)
    """
    _, timestamp = parse_timestamp(value)
    if timestamp is None:
        return 999999  # No timestamp = very old

    try:
        entry_date = datetime.strptime(timestamp, "%Y-%m-%d")
        age = (datetime.now() - entry_date).days
        return max(0, age)
    except ValueError as e:
        logger.warning(f"[learnings_manager] Failed to parse entry timestamp: {e}")
        return 999999


# =============================================================================
# KEY_LEARNINGS LOCATION
# =============================================================================


def _find_learnings_location(data: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, str]:
    """
    Find key_learnings in data structure

    Checks both root level and inside active_tasks (legacy location).

    Args:
        data: Parsed JSON data

    Returns:
        Tuple of (parent_dict containing key_learnings, location_name)
        Returns (None, '') if not found
    """
    # Check root level first
    if "key_learnings" in data:
        return (data, "root")

    # Check inside active_tasks (legacy devpulse structure)
    if "active_tasks" in data and isinstance(data["active_tasks"], dict):
        if "key_learnings" in data["active_tasks"]:
            return (data["active_tasks"], "active_tasks")

    return (None, "")


def _get_learnings(data: Dict[str, Any]) -> list | Dict[str, str]:
    """
    Get key_learnings from data regardless of location.

    Returns list (v3 unified schema) or dict (legacy).
    """
    parent, _ = _find_learnings_location(data)
    if parent is None:
        return []
    kl = parent.get("key_learnings", [])
    return kl if isinstance(kl, (list, dict)) else []


def _set_learnings(data: Dict[str, Any], learnings: list | Dict[str, str]) -> bool:
    """
    Set key_learnings in data at correct location.

    Accepts list (v3) or dict (legacy).
    """
    parent, _ = _find_learnings_location(data)
    if parent is None:
        data["key_learnings"] = learnings
        return True
    parent["key_learnings"] = learnings
    return True


# =============================================================================
# CONFIG OPERATIONS
# =============================================================================


def get_max_learnings(data: Dict[str, Any]) -> int:
    """
    Get max_entries limit from file metadata

    Priority:
    1. document_metadata.limits.max_learnings
    2. DEFAULT_MAX_ENTRIES (100)

    Args:
        data: Parsed JSON data from .local.json

    Returns:
        Maximum allowed key_learnings entries
    """
    limits = data.get("document_metadata", {}).get("limits", {})
    return limits.get("max_learnings", DEFAULT_MAX_LEARNINGS)


# =============================================================================
# RECENTLY_COMPLETED LOCATION
# =============================================================================


def _find_recently_completed_location(data: Dict[str, Any]) -> Tuple[Dict[str, Any] | None, str]:
    """
    Find recently_completed in data structure.

    Checks both root level and inside active_tasks.

    Args:
        data: Parsed JSON data

    Returns:
        Tuple of (parent_dict containing recently_completed, location_name)
        Returns (None, '') if not found
    """
    # Check root level first
    if "recently_completed" in data:
        return (data, "root")

    # Check inside active_tasks (devpulse structure)
    if "active_tasks" in data and isinstance(data["active_tasks"], dict):
        if "recently_completed" in data["active_tasks"]:
            return (data["active_tasks"], "active_tasks")

    return (None, "")


def _get_recently_completed(data: Dict[str, Any]) -> List[str]:
    """
    Get recently_completed from data regardless of location.

    Args:
        data: Parsed JSON data

    Returns:
        recently_completed list, or empty list if not found
    """
    parent, _ = _find_recently_completed_location(data)
    if parent is None:
        return []
    return parent.get("recently_completed", [])


def _set_recently_completed(data: Dict[str, Any], completed: List[str]) -> bool:
    """
    Set recently_completed in data at correct location.

    Args:
        data: Parsed JSON data
        completed: New recently_completed list

    Returns:
        True if set successfully, False if no location found
    """
    parent, _ = _find_recently_completed_location(data)
    if parent is None:
        # Create at root level if not exists
        data["recently_completed"] = completed
        return True
    parent["recently_completed"] = completed
    return True


def get_max_recently_completed(data: Dict[str, Any]) -> int:
    """
    Get max_recently_completed limit from file metadata.

    Priority:
    1. document_metadata.limits.max_recently_completed
    2. DEFAULT_MAX_RECENTLY_COMPLETED (20)

    Args:
        data: Parsed JSON data from .local.json

    Returns:
        Maximum allowed recently_completed entries
    """
    limits = data.get("document_metadata", {}).get("limits", {})
    return limits.get("max_recently_completed", DEFAULT_MAX_RECENTLY_COMPLETED)


# =============================================================================
# VECTORIZATION
# =============================================================================


def _vectorize_learnings(branch: str, learnings: List[Tuple[str, str]]) -> Dict[str, Any]:
    """
    Vectorize key_learnings entries to memory

    Args:
        branch: Branch name (e.g., "DEVPULSE")
        learnings: List of (key, value) tuples to vectorize

    Returns:
        Dict with success status
    """
    if not learnings:
        return {"success": True, "message": "No learnings to vectorize"}

    # Prepare texts and metadata for vectorization
    texts = []
    metadatas = []

    for key, value in learnings:
        clean_value, timestamp = parse_timestamp(value)
        text = f"{key}: {clean_value}"
        texts.append(text)
        metadatas.append(
            {
                "branch": branch,
                "type": "key_learning",
                "key": key,
                "timestamp": timestamp or "unknown",
                "archived_at": datetime.now().isoformat(),
            }
        )

    # Generate embeddings via subprocess
    try:
        from aipass.memory.apps.handlers.vector import embedder

        embed_result = embedder.encode_batch(texts)

        if not embed_result["success"]:
            return {"success": False, "error": f"Embedding failed: {embed_result.get('error')}"}

        embeddings = embed_result.get("embeddings", [])
        if not embeddings:
            return {"success": False, "error": "No embeddings generated"}

    except Exception as e:
        logger.warning(f"[learnings_manager] Embedding error for key_learnings: {e}")
        return {"success": False, "error": f"Embedding error: {e}"}

    # Store in ChromaDB via subprocess
    embeddings_serializable = [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    input_data = {
        "operation": "store_vectors",
        "branch": branch,
        "memory_type": "key_learnings",
        "embeddings": embeddings_serializable,
        "documents": texts,
        "metadatas": metadatas,
        "db_path": None,  # Global memory
    }

    try:
        result = subprocess.run(
            [sys.executable, str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Subprocess failed"}

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        logger.warning("[learnings_manager] Key learnings vectorization timed out")
        return {"success": False, "error": "Vectorization timed out"}
    except json.JSONDecodeError as e:
        logger.warning(f"[learnings_manager] Invalid JSON from key_learnings vectorization: {e}")
        return {"success": False, "error": f"Invalid JSON response: {e}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Key learnings vectorization error: {e}")
        return {"success": False, "error": str(e)}


def _vectorize_completed_tasks(branch: str, tasks: List[str]) -> Dict[str, Any]:
    """
    Vectorize recently_completed entries to memory.

    Args:
        branch: Branch name (e.g., "DEVPULSE")
        tasks: List of task strings to vectorize

    Returns:
        Dict with success status
    """
    if not tasks:
        return {"success": True, "message": "No tasks to vectorize"}

    # Prepare document_texts and document_metadatas for vectorization
    document_texts: List[str] = []
    document_metadatas: List[Dict[str, Any]] = []

    for task in tasks:
        clean_value, timestamp = parse_timestamp(task)
        document_texts.append(clean_value)
        document_metadatas.append(
            {
                "branch": branch,
                "type": "recently_completed",
                "timestamp": timestamp or "unknown",
                "archived_at": datetime.now().isoformat(),
            }
        )

    # Generate embeddings via subprocess
    try:
        from aipass.memory.apps.handlers.vector import embedder

        embed_result = embedder.encode_batch(document_texts)

        if not embed_result["success"]:
            return {"success": False, "error": f"Embedding failed: {embed_result.get('error')}"}

        embeddings = embed_result.get("embeddings", [])
        if not embeddings:
            return {"success": False, "error": "No embeddings generated"}

    except Exception as e:
        logger.warning(f"[learnings_manager] Embedding error for recently_completed: {e}")
        return {"success": False, "error": f"Embedding error: {e}"}

    # Store in ChromaDB via subprocess
    embeddings_serializable = [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    input_data = {
        "operation": "store_vectors",
        "branch": branch,
        "memory_type": "recently_completed",
        "embeddings": embeddings_serializable,
        "documents": document_texts,
        "metadatas": document_metadatas,
        "db_path": None,  # Global memory
    }

    try:
        result = subprocess.run(
            [sys.executable, str(CHROMA_SUBPROCESS_SCRIPT)],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            return {"success": False, "error": result.stderr or "Subprocess failed"}

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        logger.warning("[learnings_manager] Completed tasks vectorization timed out")
        return {"success": False, "error": "Vectorization timed out"}
    except json.JSONDecodeError as e:
        logger.warning(f"[learnings_manager] Invalid JSON from completed tasks vectorization: {e}")
        return {"success": False, "error": f"Invalid JSON response: {e}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Completed tasks vectorization error: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# CORE OPERATIONS
# =============================================================================


def ensure_timestamps(file_path: Path) -> Dict[str, Any]:
    """
    Ensure all key_learnings entries have timestamps

    Adds today's date to any entries missing timestamps.

    Args:
        file_path: Path to .local.json file

    Returns:
        Dict with update status and count
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        data = read_memory_file_data(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to read file: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    learnings = _get_learnings(data)
    if not learnings:
        return {"success": True, "updated": 0, "message": "No key_learnings found"}

    updated_count = 0
    today = datetime.now().strftime("%Y-%m-%d")

    if isinstance(learnings, list):
        for entry in learnings:
            if isinstance(entry, dict) and "date" not in entry:
                entry["date"] = today
                updated_count += 1
    else:
        for key, value in learnings.items():
            _, timestamp = parse_timestamp(value)
            if timestamp is None:
                learnings[key] = add_timestamp(value, today)
                updated_count += 1

    if updated_count > 0:
        _set_learnings(data, learnings)
        try:
            write_memory_file_simple(file_path, data)
        except Exception as e:
            logger.warning(f"[learnings_manager] Failed to write file: {e}")
            return {"success": False, "error": f"Failed to write file: {e}"}

    return {"success": True, "updated": updated_count, "total": len(learnings)}


def enforce_limit(file_path: Path) -> Dict[str, Any]:
    """
    Enforce max_entries limit on key_learnings

    If over limit:
    1. Sort entries by age (oldest first)
    2. Vectorize oldest entries to memory
    3. Remove oldest entries until under limit

    Args:
        file_path: Path to .local.json file

    Returns:
        Dict with enforcement status
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        data = read_memory_file_data(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to read file: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    learnings = _get_learnings(data)
    if not learnings:
        return {"success": True, "removed": 0, "message": "No key_learnings found"}

    max_entries = get_max_learnings(data)
    current_count = len(learnings)

    if current_count <= max_entries:
        return {
            "success": True,
            "removed": 0,
            "current": current_count,
            "max": max_entries,
            "message": "Under limit, no action needed",
        }

    # Extract branch name from filename
    parts = file_path.stem.split(".")
    branch_name = parts[0] if parts else "UNKNOWN"

    to_remove_count = current_count - max_entries

    if isinstance(learnings, list):
        # v3 list: oldest entries are at the end (lowest number)
        to_remove_entries = learnings[-to_remove_count:]
        to_keep_entries = learnings[:-to_remove_count]
        to_vectorize = [(e.get("key", ""), e.get("value", "")) for e in to_remove_entries if isinstance(e, dict)]
        removed_keys = [e.get("key", "") for e in to_remove_entries if isinstance(e, dict)]
        vectorize_result = _vectorize_learnings(branch_name, to_vectorize)
        _set_learnings(data, to_keep_entries)
    else:
        # Legacy dict: sort by age, oldest first
        sorted_entries = sorted(
            learnings.items(),
            key=lambda x: get_entry_age(x[1]),
            reverse=True,
        )
        to_remove = sorted_entries[:to_remove_count]
        to_keep = sorted_entries[to_remove_count:]
        removed_keys = [k for k, _ in to_remove]
        vectorize_result = _vectorize_learnings(branch_name, to_remove)
        _set_learnings(data, dict(to_keep))

    try:
        write_memory_file_simple(file_path, data)
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to write file: {e}")
        return {"success": False, "error": f"Failed to write file: {e}"}

    remaining = current_count - to_remove_count
    json_handler.log_operation("enforce_limit", {"removed": to_remove_count, "remaining": remaining, "success": True})

    return {
        "success": True,
        "removed": to_remove_count,
        "vectorized": vectorize_result.get("success", False),
        "remaining": remaining,
        "max": max_entries,
        "removed_keys": removed_keys,
    }


# =============================================================================
# RECENTLY_COMPLETED OPERATIONS
# =============================================================================


def ensure_timestamps_completed(file_path: Path) -> Dict[str, Any]:
    """
    Ensure all recently_completed entries have timestamps.

    Adds today's date to any entries missing timestamps.

    Args:
        file_path: Path to .local.json file

    Returns:
        Dict with update status and count
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        data = read_memory_file_data(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to read file: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    completed = _get_recently_completed(data)
    if not completed:
        return {"success": True, "updated": 0, "message": "No recently_completed found"}

    updated_count = 0
    today = datetime.now().strftime("%Y-%m-%d")
    updated_list: List[str] = []

    for task in completed:
        _, timestamp = parse_timestamp(task)
        if timestamp is None:
            updated_list.append(add_timestamp(task, today))
            updated_count += 1
        else:
            updated_list.append(task)

    if updated_count > 0:
        _set_recently_completed(data, updated_list)
        try:
            write_memory_file_simple(file_path, data)
        except Exception as e:
            logger.warning(f"[learnings_manager] Failed to write file: {e}")
            return {"success": False, "error": f"Failed to write file: {e}"}

    return {"success": True, "updated": updated_count, "total": len(completed)}


def enforce_limit_completed(file_path: Path) -> Dict[str, Any]:
    """
    Enforce max_recently_completed limit.

    If over limit:
    1. Sort entries by age (oldest first)
    2. Vectorize oldest entries to memory
    3. Remove oldest entries until under limit

    Args:
        file_path: Path to .local.json file

    Returns:
        Dict with enforcement status
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        data = read_memory_file_data(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to read file: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    completed = _get_recently_completed(data)
    if not completed:
        return {"success": True, "removed": 0, "message": "No recently_completed found"}

    max_entries = get_max_recently_completed(data)
    current_count = len(completed)

    if current_count <= max_entries:
        return {
            "success": True,
            "removed": 0,
            "current": current_count,
            "max": max_entries,
            "message": "Under limit, no action needed",
        }

    # Sort by age (oldest first) - for lists, we use index as proxy
    # Entries with timestamps get sorted, entries without go first (oldest)
    sorted_entries = sorted(
        completed,
        key=lambda x: get_entry_age(x),
        reverse=True,  # Oldest first
    )

    # Calculate how many to remove
    to_remove_count = current_count - max_entries
    to_remove = sorted_entries[:to_remove_count]
    to_keep = sorted_entries[to_remove_count:]

    # Extract branch name from filename
    parts = file_path.stem.split(".")
    branch_name = parts[0] if parts else "UNKNOWN"

    # Vectorize before removing
    vectorize_result = _vectorize_completed_tasks(branch_name, to_remove)

    # Update recently_completed with remaining entries
    _set_recently_completed(data, to_keep)

    try:
        write_memory_file_simple(file_path, data)
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to write file: {e}")
        return {"success": False, "error": f"Failed to write file: {e}"}

    return {
        "success": True,
        "removed": to_remove_count,
        "vectorized": vectorize_result.get("success", False),
        "remaining": len(to_keep),
        "max": max_entries,
        "removed_tasks": to_remove,
    }


# =============================================================================
# STATUS COUNT UPDATES
# =============================================================================


def update_status_counts(file_path: Path) -> Dict[str, Any]:
    """
    Update status.current_key_learnings and status.current_recently_completed.

    Reads actual counts from data and updates document_metadata.status.

    Args:
        file_path: Path to .local.json file

    Returns:
        Dict with update status
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    try:
        data = read_memory_file_data(file_path)
        if data is None:
            return {"success": False, "error": f"Failed to parse file: {file_path.name}"}
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to read file: {e}")
        return {"success": False, "error": f"Failed to read file: {e}"}

    # Get actual counts
    learnings = _get_learnings(data)
    completed = _get_recently_completed(data)
    learnings_count = len(learnings)
    completed_count = len(completed)

    # Ensure document_metadata.status exists
    if "document_metadata" not in data:
        data["document_metadata"] = {}
    if "status" not in data["document_metadata"]:
        data["document_metadata"]["status"] = {}

    status = data["document_metadata"]["status"]
    old_learnings = status.get("current_key_learnings", 0)
    old_completed = status.get("current_recently_completed", 0)

    # Update counts
    status["current_key_learnings"] = learnings_count
    status["current_recently_completed"] = completed_count
    status["last_health_check"] = datetime.now().strftime("%Y-%m-%d")

    # Only write if changed
    if old_learnings != learnings_count or old_completed != completed_count:
        try:
            write_memory_file_simple(file_path, data)
        except Exception as e:
            logger.warning(f"[learnings_manager] Failed to write file: {e}")
            return {"success": False, "error": f"Failed to write file: {e}"}

    return {
        "success": True,
        "current_key_learnings": learnings_count,
        "current_recently_completed": completed_count,
        "changed": old_learnings != learnings_count or old_completed != completed_count,
    }


# =============================================================================
# BATCH OPERATIONS
# =============================================================================


def process_file(file_path: Path) -> Dict[str, Any]:
    """
    Process a single .local.json file for both key_learnings and recently_completed.

    Steps:
    1. Ensure timestamps on key_learnings
    2. Enforce key_learnings limit
    3. Ensure timestamps on recently_completed
    4. Enforce recently_completed limit
    5. Update status counts

    Args:
        file_path: Path to .local.json file

    Returns:
        Dict with processing summary
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    results: Dict[str, Any] = {"success": True, "key_learnings": {}, "recently_completed": {}, "status": {}}

    # Process key_learnings
    timestamp_result = ensure_timestamps(file_path)
    limit_result = enforce_limit(file_path)
    results["key_learnings"] = {
        "timestamps_added": timestamp_result.get("updated", 0),
        "removed": limit_result.get("removed", 0),
        "vectorized": limit_result.get("vectorized", False),
        "remaining": limit_result.get("remaining", 0),
    }

    # Process recently_completed
    timestamp_completed = ensure_timestamps_completed(file_path)
    limit_completed = enforce_limit_completed(file_path)
    results["recently_completed"] = {
        "timestamps_added": timestamp_completed.get("updated", 0),
        "removed": limit_completed.get("removed", 0),
        "vectorized": limit_completed.get("vectorized", False),
        "remaining": limit_completed.get("remaining", 0),
        "removed_tasks": limit_completed.get("removed_tasks", []),
    }

    # Update status counts
    status_result = update_status_counts(file_path)
    results["status"] = {
        "current_key_learnings": status_result.get("current_key_learnings", 0),
        "current_recently_completed": status_result.get("current_recently_completed", 0),
    }

    # Check for errors
    if not timestamp_result["success"]:
        results["success"] = False
        results["error"] = timestamp_result.get("error")
    if not limit_result["success"]:
        results["success"] = False
        results["error"] = limit_result.get("error")
    if not timestamp_completed["success"]:
        results["success"] = False
        results["error"] = timestamp_completed.get("error")
    if not limit_completed["success"]:
        results["success"] = False
        results["error"] = limit_completed.get("error")

    return results


def process_all_branches() -> Dict[str, Any]:
    """
    Process key_learnings and recently_completed for all branches in registry.

    For each branch:
    1. Ensure timestamps on all entries
    2. Enforce max_entries limits
    3. Update status counts

    Returns:
        Dict with processing summary
    """
    registry_path = _find_repo_root() / "AIPASS_REGISTRY.json"

    if not registry_path.exists():
        return {"success": False, "error": "AIPASS_REGISTRY.json not found"}

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            registry = json.load(f)
    except Exception as e:
        logger.warning(f"[learnings_manager] Failed to read registry: {e}")
        return {"success": False, "error": f"Failed to read registry: {e}"}

    branches = registry.get("branches", [])
    results: Dict[str, Any] = {"success": True, "processed": 0, "skipped": 0, "errors": [], "details": {}}

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")
        branch_path = Path(branch.get("path", ""))

        if not branch_path.exists():
            results["skipped"] += 1
            continue

        # Find .local.json file
        local_file = branch_path / f"{branch_name.upper()}.local.json"
        if not local_file.exists():
            results["skipped"] += 1
            continue

        # Process this branch
        branch_result = process_file(local_file)

        results["processed"] += 1
        results["details"][branch_name] = branch_result

        if not branch_result["success"]:
            results["errors"].append(f"{branch_name}: {branch_result.get('error')}")

    return results


# =============================================================================
# STANDALONE EXECUTION
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Memory Sections Management Handler")
    parser.add_argument(
        "command",
        choices=[
            "timestamps",
            "enforce",
            "process-all",
            "process-file",
            "timestamps-completed",
            "enforce-completed",
            "update-status",
        ],
        help="Command to execute",
    )
    parser.add_argument("--file", type=Path, help="Path to .local.json file")

    args = parser.parse_args()

    if args.command == "process-all":
        result = process_all_branches()
        print(json.dumps(result, indent=2))

    elif args.command == "process-file":
        if not args.file:
            print("Error: --file required for process-file command")
            sys.exit(1)
        result = process_file(args.file)
        print(json.dumps(result, indent=2))

    elif args.command == "timestamps":
        if not args.file:
            print("Error: --file required for timestamps command")
            sys.exit(1)
        result = ensure_timestamps(args.file)
        print(json.dumps(result, indent=2))

    elif args.command == "enforce":
        if not args.file:
            print("Error: --file required for enforce command")
            sys.exit(1)
        result = enforce_limit(args.file)
        print(json.dumps(result, indent=2))

    elif args.command == "timestamps-completed":
        if not args.file:
            print("Error: --file required for timestamps-completed command")
            sys.exit(1)
        result = ensure_timestamps_completed(args.file)
        print(json.dumps(result, indent=2))

    elif args.command == "enforce-completed":
        if not args.file:
            print("Error: --file required for enforce-completed command")
            sys.exit(1)
        result = enforce_limit_completed(args.file)
        print(json.dumps(result, indent=2))

    elif args.command == "update-status":
        if not args.file:
            print("Error: --file required for update-status command")
            sys.exit(1)
        result = update_status_counts(args.file)
        print(json.dumps(result, indent=2))
