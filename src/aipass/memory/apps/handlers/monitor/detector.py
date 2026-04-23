# =================== AIPass ====================
# Name: detector.py
# Description: Rollover Trigger Detection Handler
# Version: 0.2.0
# Created: 2025-11-16
# Modified: 2026-03-06
# =============================================

"""
Rollover Trigger Detection Handler

Monitors branch memory files via AIPASS_REGISTRY.json and detects when
files exceed their max_lines threshold (typically 600 lines).

Purpose:
    Detect rollover conditions without active monitoring. Called by
    rollover module to check all branches for files needing rollover.

Independence:
    No module imports - pure handler, transportable
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler

logger = get_system_logger()

# No service imports - handlers are pure workers (3-tier architecture)
# No module imports (handler independence)


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


_REPO_ROOT = _find_repo_root()


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class RolloverTrigger:
    """Represents a file that needs rollover"""

    branch: str
    memory_type: str  # 'observations' or 'local'
    file_path: Path
    current_lines: int
    max_lines: int
    schema_version: str = "1.0.0"
    v2_reason: str = ""

    def __str__(self):
        if self.schema_version.startswith("2") and self.v2_reason:
            return f"{self.branch}.{self.memory_type} ({self.v2_reason})"
        return f"{self.branch}.{self.memory_type} ({self.current_lines}/{self.max_lines} lines)"


# =============================================================================
# REGISTRY OPERATIONS
# =============================================================================


def _read_registry() -> List[Dict[str, Any]]:
    """
    Read AIPASS_REGISTRY.json from repo root.

    Registry paths are relative — resolved against repo root.

    Returns:
        List of branch dictionaries with absolute paths
    """
    registry_path = _REPO_ROOT / "AIPASS_REGISTRY.json"

    if not registry_path.exists():
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            branches = data.get("branches", [])

            # Resolve relative paths against repo root
            for branch in branches:
                raw_path = branch.get("path", "")
                resolved = Path(raw_path)
                if not resolved.is_absolute():
                    resolved = _REPO_ROOT / raw_path
                branch["path"] = str(resolved)

            return branches
    except Exception as e:
        logger.warning(f"[detector] Failed to read registry: {e}")
        return []


def _get_memory_file_path(branch: Dict, memory_type: str) -> Path | None:
    """
    Get path to memory file for branch.

    Memory files live in .trinity/ subdirectory as {memory_type}.json
    (e.g., .trinity/local.json, .trinity/observations.json).

    Args:
        branch: Branch dict from registry (path already resolved to absolute)
        memory_type: 'observations' or 'local'

    Returns:
        Path to memory file, or None if not found
    """
    raw_path = branch.get("path", "")
    if not raw_path:
        return None
    branch_path = Path(raw_path)
    if not branch_path.exists():
        return None

    # Memory files are in .trinity/ subdirectory
    file_path = branch_path / ".trinity" / f"{memory_type}.json"

    return file_path if file_path.exists() else None


# =============================================================================
# CONFIG LOADING
# =============================================================================


def _load_config() -> Dict[str, Any]:
    """
    Load memory_bank.config.json

    Returns:
        Config dict, or empty dict on error
    """
    # Look for config relative to this handler's location
    config_path = Path(__file__).resolve().parents[3] / "config" / "memory_bank.config.json"

    if not config_path.exists():
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[detector] Failed to load config: {e}")
        return {}


# =============================================================================
# LINE COUNTING
# =============================================================================


def _count_file_lines(file_path: Path) -> int:
    """
    Count physical lines in memory file

    Args:
        file_path: Path to JSON file

    Returns:
        Number of physical lines in file
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return len(f.readlines())
    except Exception as e:
        logger.warning(f"[detector] Failed to count lines in {file_path}: {e}")
        return 0


def _get_max_lines(file_path: Path, branch_name: str | None = None) -> int:
    """
    Get max_lines limit with priority: file metadata > branch config > default

    Args:
        file_path: Path to JSON file
        branch_name: Optional branch name for config lookup

    Returns:
        Max lines limit (default 600)
    """
    # 1. Try file-level metadata first (highest priority)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            metadata = data.get("document_metadata", {})
            limits = metadata.get("limits", {})
            file_limit = limits.get("max_lines")
            if file_limit is not None:
                return file_limit
    except Exception as e:
        logger.warning(f"[detector] Failed to read file-level max_lines from {file_path}: {e}")

    # 2. Try branch-level config (if branch_name provided or can be extracted)
    if branch_name is None:
        # Extract from filename (e.g., SEEDGO.local.json -> SEEDGO)
        parts = file_path.stem.split(".")
        branch_name = parts[0] if parts else None

    if branch_name:
        config = _load_config()
        branch_limits = config.get("rollover", {}).get("per_branch", {}).get(branch_name, {})
        if "max_lines" in branch_limits:
            return branch_limits["max_lines"]

    # 3. Fall back to global default from config
    config = _load_config()
    default_limit = config.get("rollover", {}).get("defaults", {}).get("max_lines")
    if default_limit is not None:
        return default_limit

    # 4. Final fallback to hardcoded 600
    return 600


# =============================================================================
# ROLLOVER DETECTION
# =============================================================================


def _should_rollover(file_path: Path) -> tuple[bool, int, int, str, str]:
    """
    Check if file should rollover (supports v1 line-based and v2 entry-count based).

    Args:
        file_path: Path to memory JSON file

    Returns:
        Tuple of (should_rollover, current_lines, max_lines, schema_version, v2_reason)
        For v2 files, max_lines is 0 and v2_reason describes which limits are exceeded.
    """
    current_lines = _count_file_lines(file_path)

    # Read file data once for schema detection + limit checks
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # Can't parse — fall back to line-based with hardcoded default
        logger.warning(f"[detector] Failed to parse {file_path} for rollover check: {e}")
        return (current_lines >= 600, current_lines, 600, "1.0.0", "")

    metadata = data.get("document_metadata", {})
    schema_version = metadata.get("schema_version", "1.0.0")
    limits = metadata.get("limits", {})

    # v2: entry-count based limits
    if schema_version.startswith("2"):
        reasons = []

        max_sessions = limits.get("max_sessions")
        if max_sessions is not None:
            sessions = data.get("sessions", [])
            if isinstance(sessions, list) and len(sessions) >= max_sessions:
                reasons.append(f"{len(sessions)}/{max_sessions} sessions")

        max_key_learnings = limits.get("max_key_learnings")
        if max_key_learnings is not None:
            key_learnings = data.get("key_learnings", {})
            if isinstance(key_learnings, dict) and len(key_learnings) >= max_key_learnings:
                reasons.append(f"{len(key_learnings)}/{max_key_learnings} key_learnings")

        max_observations = limits.get("max_observations")
        if max_observations is not None:
            observations = data.get("observations", [])
            if isinstance(observations, list) and len(observations) >= max_observations:
                reasons.append(f"{len(observations)}/{max_observations} observations")

        triggered = len(reasons) > 0
        return (triggered, current_lines, 0, schema_version, ", ".join(reasons))

    # v1: line-count based
    max_lines = limits.get("max_lines")
    if max_lines is None:
        max_lines = _get_max_lines(file_path)

    return (current_lines >= max_lines, current_lines, max_lines, "1.0.0", "")


def check_all_branches() -> Dict[str, Any]:
    """
    Check all branches for rollover triggers

    Scans AIPASS_REGISTRY.json and checks each branch's memory files
    (observations and local) for rollover conditions.

    Returns:
        Dict with success status, triggers list, and count
    """
    triggers = []

    # Read registry
    branches = _read_registry()
    if not branches:
        return {"success": True, "triggers": [], "count": 0, "message": "No branches in registry"}

    # Check each branch
    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")

        # Check both memory types
        for memory_type in ["observations", "local"]:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue  # File doesn't exist, skip

            should_trigger, current_lines, max_lines, schema_ver, v2_reason = _should_rollover(file_path)

            if should_trigger:
                trigger = RolloverTrigger(
                    branch=branch_name,
                    memory_type=memory_type,
                    file_path=file_path,
                    current_lines=current_lines,
                    max_lines=max_lines,
                    schema_version=schema_ver,
                    v2_reason=v2_reason,
                )
                triggers.append(trigger)

    json_handler.log_operation(
        "check_all_branches", {"branches_checked": len(branches), "triggers_found": len(triggers)}
    )

    return {
        "success": True,
        "triggers": triggers,
        "count": len(triggers),
        "message": f"Found {len(triggers)} rollover triggers" if triggers else "No rollover triggers detected",
    }


def check_single_file(file_path: Path) -> Dict[str, Any]:
    """
    Check single file for rollover trigger

    Args:
        file_path: Path to memory JSON file

    Returns:
        Dict with trigger status and details
    """
    if not file_path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}

    should_trigger, current_lines, max_lines, schema_ver, v2_reason = _should_rollover(file_path)

    if should_trigger:
        # Extract branch and type from filename (e.g., SEEDGO.observations.json)
        parts = file_path.stem.split(".")
        branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
        memory_type = parts[1] if len(parts) > 1 else "unknown"

        trigger = RolloverTrigger(
            branch=branch_name,
            memory_type=memory_type,
            file_path=file_path,
            current_lines=current_lines,
            max_lines=max_lines,
            schema_version=schema_ver,
            v2_reason=v2_reason,
        )

        return {"success": True, "trigger": trigger, "should_rollover": True}
    else:
        remaining = max_lines - current_lines if max_lines > 0 else 0
        return {
            "success": True,
            "should_rollover": False,
            "current_lines": current_lines,
            "max_lines": max_lines,
            "schema_version": schema_ver,
            "remaining": remaining,
        }


# =============================================================================
# STATISTICS
# =============================================================================


def get_rollover_stats() -> Dict[str, Any]:
    """
    Get rollover statistics for all branches

    Returns:
        Dict with statistics for all branches
    """
    stats = {"success": True, "total_branches": 0, "files_checked": 0, "files_ready": 0, "branches": {}}

    branches = _read_registry()
    stats["total_branches"] = len(branches)

    for branch in branches:
        branch_name = branch.get("name", "UNKNOWN")
        branch_stats = {}

        for memory_type in ["observations", "local"]:
            file_path = _get_memory_file_path(branch, memory_type)

            if file_path is None:
                continue

            stats["files_checked"] += 1
            should_trigger, current_lines, max_lines, schema_ver, v2_reason = _should_rollover(file_path)

            stat_entry = {
                "current": current_lines,
                "max": max_lines,
                "ready": should_trigger,
                "remaining": max_lines - current_lines if max_lines > 0 else 0,
                "schema_version": schema_ver,
            }
            if v2_reason:
                stat_entry["v2_reason"] = v2_reason

            branch_stats[memory_type] = stat_entry

            if should_trigger:
                stats["files_ready"] += 1

        if branch_stats:
            stats["branches"][branch_name] = branch_stats

    return stats
