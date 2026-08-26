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
entry counts exceed v2 limits (sessions, key_learnings, observations).

Purpose:
    Detect rollover conditions without active monitoring. Called by
    rollover module to check all branches for files needing rollover.
    All branches use v2 entry-count limits from memory.config.json
    (per_branch with defaults fallback). No line-count fallbacks.

Independence:
    No module imports - pure handler, transportable
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.json import config_loader

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
_MEMORY_ROOT = Path(__file__).resolve().parents[3]
_KNOWN_REGISTRIES_PATH = _MEMORY_ROOT / "memory_json" / "known_registries.json"


def load_known_registries() -> List[Path]:
    """Load persisted external registry paths from known_registries.json.

    Returns only paths that currently exist on disk.
    """
    if not _KNOWN_REGISTRIES_PATH.exists():
        return []
    try:
        data = json.loads(_KNOWN_REGISTRIES_PATH.read_text(encoding="utf-8"))
        return [Path(p) for p in data.get("registries", []) if Path(p).exists()]
    except Exception as e:
        logger.warning(f"[detector] Failed to read known_registries.json: {e}")
        return []


def persist_registry(registry_path: Path) -> None:
    """Persist a newly discovered external registry so future runs find it."""
    current: List[str] = []
    if _KNOWN_REGISTRIES_PATH.exists():
        try:
            data = json.loads(_KNOWN_REGISTRIES_PATH.read_text(encoding="utf-8"))
            current = data.get("registries", [])
        except Exception as e:
            logger.warning(f"[detector] Failed to parse known_registries.json, starting fresh: {e}")
    resolved = str(registry_path.resolve())
    if resolved not in current:
        current.append(resolved)
        _KNOWN_REGISTRIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _KNOWN_REGISTRIES_PATH.write_text(
            json.dumps({"registries": current}, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info(f"[detector] Persisted external registry: {resolved}")


def _find_caller_registries() -> List[Path]:
    """Find all external project registries (persisted + cwd-reachable)."""
    import os

    aipass_registry = (_REPO_ROOT / "AIPASS_REGISTRY.json").resolve()
    registries: List[Path] = []
    seen: set[Path] = set()

    for reg in load_known_registries():
        resolved = reg.resolve()
        if resolved != aipass_registry and resolved not in seen:
            registries.append(reg)
            seen.add(resolved)

    caller_cwd = (
        Path(os.environ.get("AIPASS_CALLER_CWD", "")).resolve() if os.environ.get("AIPASS_CALLER_CWD") else Path.cwd()
    )

    cwd_found: List[Path] = []
    for parent in [caller_cwd] + list(caller_cwd.parents):
        for reg in parent.glob("*_REGISTRY.json"):
            if reg.resolve() != aipass_registry:
                cwd_found.append(reg)
        if cwd_found:
            break

    for reg in cwd_found:
        resolved = reg.resolve()
        if resolved not in seen:
            registries.append(reg)
            seen.add(resolved)
        persist_registry(reg)

    return registries


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass
class RolloverTrigger:
    """Represents a file that needs rollover (v2 entry-count based)"""

    branch: str
    memory_type: str  # 'observations' or 'local'
    file_path: Path
    current_lines: int
    schema_version: str = "3.0.0"
    v2_reason: str = ""

    def __str__(self):
        return f"{self.branch}.{self.memory_type} ({self.v2_reason})"


# =============================================================================
# REGISTRY OPERATIONS
# =============================================================================


def _read_single_registry(registry_path: Path, root: Path) -> List[Dict[str, Any]]:
    """Read branches from a single registry file, resolving paths against root."""
    if not registry_path.exists():
        return []

    try:
        with open(registry_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            branches = data.get("branches", [])

            for branch in branches:
                raw_path = branch.get("path", "")
                resolved = Path(raw_path)
                if not resolved.is_absolute():
                    resolved = root / raw_path
                branch["path"] = str(resolved)

            return branches
    except Exception as e:
        logger.warning(f"[detector] Failed to read registry {registry_path}: {e}")
        return []


def _read_registry() -> List[Dict[str, Any]]:
    """
    Read all project registries (AIPass + external projects from caller CWD).

    Registry paths are relative — resolved against their respective project root.

    Returns:
        List of branch dictionaries with absolute paths
    """
    branches = _read_single_registry(_REPO_ROOT / "AIPASS_REGISTRY.json", _REPO_ROOT)

    seen_paths = {b.get("path") for b in branches}
    for reg_path in _find_caller_registries():
        for branch in _read_single_registry(reg_path, reg_path.parent):
            if branch.get("path") not in seen_paths:
                branches.append(branch)
                seen_paths.add(branch.get("path"))

    return branches


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


_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"
_TEMPLATE_MAP = {
    "local": _TEMPLATES_DIR / "LOCAL.template.json",
    "observations": _TEMPLATES_DIR / "OBSERVATIONS.template.json",
}


def _recreate_trinity_file(branch_path: Path, branch_name: str, memory_type: str) -> Path | None:
    """Recreate a missing .trinity file from canonical template."""
    template_path = _TEMPLATE_MAP.get(memory_type)
    if not template_path or not template_path.exists():
        logger.warning(f"[detector] No template for {memory_type}")
        return None

    try:
        template = json.loads(template_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"[detector] Failed to read template {template_path}: {e}")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    upper_name = branch_name.upper()

    def _walk(val):
        if isinstance(val, str):
            return val.replace("{{BRANCHNAME}}", upper_name).replace("{{DATE}}", today)
        if isinstance(val, list):
            return [_walk(item) for item in val]
        if isinstance(val, dict):
            return {k: _walk(v) for k, v in val.items()}
        return val

    data = _walk(template)

    trinity_dir = branch_path / ".trinity"
    trinity_dir.mkdir(parents=True, exist_ok=True)
    file_path = trinity_dir / f"{memory_type}.json"

    try:
        file_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        logger.info(f"[detector] Recreated {file_path}")
        json_handler.log_operation(
            "recreate_trinity_file",
            {"branch": branch_name, "type": memory_type, "path": str(file_path)},
        )
        return file_path
    except OSError as e:
        logger.warning(f"[detector] Failed to write {file_path}: {e}")
        return None


# =============================================================================
# ROLLOVER DETECTION
# =============================================================================


def _should_rollover(file_path: Path) -> tuple[bool, int, str, str]:
    """
    Check if file should rollover (v2 entry-count based only).

    All branches use v2 entry-count limits from config (per_branch with
    defaults fallback). No line-count fallbacks — errors over silent fallbacks.

    Fires only ABOVE the limit, never at it: keep-15 means the file is allowed
    to hold 15. This threshold and rollover/extractor.py's `_extract_tail_excess`
    are one decision in two places — the extractor drains `len - limit`, so a
    detector firing at `>=` would flag a file the extractor correctly refuses to
    touch, and the pair would spin on it forever (NOTHING DRAINED). Pinned by
    `test_detector_and_extractor_never_disagree`, swept across the boundary.

    Args:
        file_path: Path to memory JSON file

    Returns:
        Tuple of (should_rollover, current_lines, schema_version, v2_reason)
    """
    current_lines = _count_file_lines(file_path)

    # Read file data once for limit checks
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # Can't parse — do NOT fall back to 600. Fail honestly.
        logger.warning(f"[detector] PARSE FAILURE for {file_path}: {e} — skipping rollover check")
        return (False, current_lines, "3.0.0", "parse failure — skipped")

    # Derive branch name from file path: .trinity/local.json → parent of .trinity
    if file_path.parent.name == ".trinity":
        branch_name = file_path.parents[1].name.lower()
    else:
        branch_name = file_path.stem.split(".")[0].lower()

    # Determine file type from filename
    file_type = file_path.stem.split(".")[0] if file_path.parent.name == ".trinity" else file_path.stem.split(".")[-1]
    # .trinity/local.json → "local"; .trinity/observations.json → "observations"

    cfg = config_loader.section("rollover")
    per_branch = cfg.get("per_branch", {})
    defaults = cfg.get("defaults", {})

    # v2 lookup: per_branch[branch][file_type], fallback to defaults[file_type]
    file_limits = per_branch.get(branch_name, {}).get(file_type, {})
    if not file_limits:
        file_limits = defaults.get(file_type, {})

    if not file_limits:
        # Neither per_branch NOR defaults have limits for this branch/file_type
        logger.warning(
            f"[detector] CONFIG GAP: no v2 limits for branch={branch_name} file_type={file_type} "
            f"in per_branch or defaults — skipping rollover"
        )
        return (False, current_lines, "3.0.0", f"config gap for {branch_name}/{file_type}")

    reasons = []

    session_limits = file_limits.get("sessions", {})
    max_sessions = session_limits.get("count")
    auto_compact_cap = session_limits.get("auto_compact_cap")
    if max_sessions is not None or auto_compact_cap is not None:
        sessions = data.get("sessions", [])
        if isinstance(sessions, list):
            auto_count = sum(1 for e in sessions if isinstance(e, dict) and e.get("status") == "auto-compact")
            regular_count = len(sessions) - auto_count
            if auto_compact_cap is not None and auto_count > auto_compact_cap:
                reasons.append(f"{auto_count}/{auto_compact_cap} auto-compact snapshots")
            if max_sessions is not None and regular_count > max_sessions:
                reasons.append(f"{regular_count}/{max_sessions} sessions")

    max_key_learnings = file_limits.get("key_learnings", {}).get("count")
    if max_key_learnings is not None:
        key_learnings = data.get("key_learnings", [])
        if isinstance(key_learnings, (list, dict)) and len(key_learnings) > max_key_learnings:
            reasons.append(f"{len(key_learnings)}/{max_key_learnings} key_learnings")

    max_observations = file_limits.get("observations", {}).get("count")
    if max_observations is not None:
        observations = data.get("observations", [])
        if isinstance(observations, list) and len(observations) > max_observations:
            reasons.append(f"{len(observations)}/{max_observations} observations")

    if reasons:
        return (True, current_lines, "3.0.0", ", ".join(reasons))

    return (False, current_lines, "3.0.0", "")


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
                branch_path = Path(branch.get("path", ""))
                if branch_path.exists():
                    file_path = _recreate_trinity_file(branch_path, branch_name, memory_type)
                if file_path is None:
                    continue

            should_trigger, current_lines, schema_ver, v2_reason = _should_rollover(file_path)

            if should_trigger:
                trigger = RolloverTrigger(
                    branch=branch_name,
                    memory_type=memory_type,
                    file_path=file_path,
                    current_lines=current_lines,
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

    should_trigger, current_lines, schema_ver, v2_reason = _should_rollover(file_path)

    if should_trigger:
        # Extract branch and type from file path
        if file_path.parent.name == ".trinity":
            branch_name = file_path.parents[1].name
            memory_type = file_path.stem  # "local" or "observations"
        else:
            # Legacy flat files: SEEDGO.observations.json
            parts = file_path.stem.split(".")
            branch_name = parts[0] if len(parts) > 0 else "UNKNOWN"
            memory_type = parts[1] if len(parts) > 1 else "unknown"

        trigger = RolloverTrigger(
            branch=branch_name,
            memory_type=memory_type,
            file_path=file_path,
            current_lines=current_lines,
            schema_version=schema_ver,
            v2_reason=v2_reason,
        )

        return {"success": True, "trigger": trigger, "should_rollover": True}
    else:
        return {
            "success": True,
            "should_rollover": False,
            "current_lines": current_lines,
            "schema_version": schema_ver,
            "v2_reason": v2_reason,
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
            should_trigger, current_lines, schema_ver, v2_reason = _should_rollover(file_path)

            stat_entry: Dict[str, Any] = {
                "current": current_lines,
                "ready": should_trigger,
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
