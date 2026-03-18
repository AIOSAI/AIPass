# =================== AIPass ====================
# Name: dashboard_push.py
# Description: Memory Bank Dashboard Write-Through
# Version: 0.2.0
# Created: 2026-02-25
# Modified: 2026-03-06
# =============================================

"""
Memory Bank Dashboard Write-Through Handler

Pushes the memory_bank section to branch dashboards.
Called after rollover, pool processing, and plans processing to keep dashboards
showing accurate vector counts, collection stats, and near-rollover warnings.

This is a SYSTEM-WIDE push: Memory Bank data is global, so it pushes to ALL
branch dashboards (every branch benefits from knowing system memory health).
"""

import sys
import logging
import subprocess
from json import loads as json_loads
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

from aipass.prax.apps.modules.logger import get_system_logger
from aipass.memory.apps.handlers.json.json_handler import log_operation

logger = get_system_logger()

# Resolve paths relative to handler location
_MEMORY_ROOT = Path(__file__).resolve().parents[3]


# =============================================================================
# CONSTANTS
# =============================================================================

CENTRAL_FILE = _MEMORY_ROOT / "central" / "memory_bank.central.json"
CONFIG_PATH = _MEMORY_ROOT / "config" / "memory_bank.config.json"
TEMPLATE_VERSION_FILE = _MEMORY_ROOT / "templates" / ".template_version.json"


def _find_repo_root() -> Path:
    """Walk up from this file to find repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"

# Near-rollover threshold: branches with fewer than this many lines remaining
NEAR_ROLLOVER_THRESHOLD = 100


# =============================================================================
# DATA COLLECTION
# =============================================================================

def _read_central_stats() -> Dict[str, Any]:
    """
    Read total_vectors and related stats from memory central.json.

    Returns:
        Dict with total_vectors, total_archives, last_rollover
    """
    try:
        if not CENTRAL_FILE.exists():
            return {"total_vectors": 0, "total_archives": 0, "last_rollover": ""}

        data = json_loads(CENTRAL_FILE.read_text(encoding="utf-8"))
        stats = data.get("stats", {})
        return {
            "total_vectors": stats.get("total_vectors", 0),
            "total_archives": stats.get("total_archives", 0),
            "last_rollover": stats.get("last_rollover", "")
        }
    except Exception:
        return {"total_vectors": 0, "total_archives": 0, "last_rollover": ""}


def _get_collections_count() -> int:
    """
    Count ChromaDB collections by reading the SQLite database directly.

    Returns:
        Number of collections in the global Chroma database
    """
    try:
        import sqlite3

        db_file = _MEMORY_ROOT / ".chroma" / "chroma.sqlite3"
        if not db_file.exists():
            return 0

        conn = sqlite3.connect(str(db_file))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM collections")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def _get_rollover_config() -> Dict[str, Any]:
    """
    Load rollover configuration (defaults + per-branch overrides).

    Returns:
        Dict with 'defaults' and 'per_branch' rollover config
    """
    try:
        if not CONFIG_PATH.exists():
            return {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}

        data = json_loads(CONFIG_PATH.read_text(encoding="utf-8"))
        rollover = data.get("rollover", {})
        return {
            "defaults": rollover.get("defaults", {"max_lines": 600, "buffer": 100}),
            "per_branch": rollover.get("per_branch", {})
        }
    except Exception:
        return {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}


def _get_max_lines_for_branch(branch_name: str, rollover_config: Dict) -> int:
    """
    Get the max_lines limit for a specific branch, respecting per-branch overrides.

    Args:
        branch_name: Uppercase branch name
        rollover_config: Rollover config dict from _get_rollover_config()

    Returns:
        Max lines for this branch
    """
    per_branch = rollover_config.get("per_branch", {})
    if branch_name in per_branch:
        return per_branch[branch_name].get("max_lines", rollover_config["defaults"]["max_lines"])
    return rollover_config["defaults"]["max_lines"]


def _find_branches_near_rollover() -> List[Dict[str, Any]]:
    """
    Scan all branches to find those near their rollover threshold.

    Reads document_metadata.status.current_lines from each *.local.json
    and *.observations.json, compares against max_lines limit.

    Returns:
        List of dicts with branch, file_type, lines_remaining
    """
    near_rollover: List[Dict[str, Any]] = []

    try:
        if not AIPASS_REGISTRY.exists():
            return near_rollover

        registry = json_loads(AIPASS_REGISTRY.read_text(encoding="utf-8"))
        branches = registry.get("branches", [])
        rollover_config = _get_rollover_config()

        repo_root = _find_repo_root()
        for branch in branches:
            branch_name = branch.get("name", "")
            raw_path = branch.get("path", "")
            branch_path = Path(raw_path)
            if not branch_path.is_absolute():
                branch_path = repo_root / raw_path

            if not branch_path.exists():
                continue

            max_lines = _get_max_lines_for_branch(branch_name, rollover_config)

            # Memory files live in .trinity/ subdirectory
            for suffix in ["local", "observations"]:
                memory_file = branch_path / ".trinity" / f"{suffix}.json"
                if not memory_file.exists():
                    continue

                try:
                    data = json_loads(memory_file.read_text(encoding="utf-8"))
                    doc_meta = data.get("document_metadata", {})
                    schema_version = doc_meta.get("schema_version", "1.0.0")
                    limits = doc_meta.get("limits", {})

                    # v2: check entry counts instead of line counts
                    if schema_version.startswith("2"):
                        max_sessions = limits.get("max_sessions")
                        if max_sessions is not None:
                            sessions = data.get("sessions", [])
                            remaining_sessions = max_sessions - len(sessions)
                            if remaining_sessions < 3:
                                near_rollover.append({
                                    "branch": branch_name,
                                    "file_type": suffix,
                                    "lines_remaining": remaining_sessions,
                                    "current_lines": len(sessions),
                                    "max_lines": max_sessions,
                                    "v2_field": "sessions",
                                })
                        max_kl = limits.get("max_key_learnings")
                        if max_kl is not None:
                            kl = data.get("key_learnings", {})
                            remaining_kl = max_kl - len(kl)
                            if remaining_kl < 3:
                                near_rollover.append({
                                    "branch": branch_name,
                                    "file_type": suffix,
                                    "lines_remaining": remaining_kl,
                                    "current_lines": len(kl),
                                    "max_lines": max_kl,
                                    "v2_field": "key_learnings",
                                })
                        continue

                    # v1: line-count based
                    status = doc_meta.get("status", {})
                    current_lines = status.get("current_lines")

                    if current_lines is None:
                        continue

                    remaining = max_lines - current_lines
                    if remaining < NEAR_ROLLOVER_THRESHOLD:
                        near_rollover.append({
                            "branch": branch_name,
                            "file_type": suffix,
                            "lines_remaining": max(remaining, 0),
                            "current_lines": current_lines,
                            "max_lines": max_lines
                        })
                except Exception:
                    # Skip files that can't be read
                    continue

    except Exception:
        return near_rollover  # Return partial results on registry read failure

    # Sort by lines_remaining ascending (most urgent first)
    near_rollover.sort(key=lambda x: x["lines_remaining"])
    return near_rollover


def _get_template_version() -> str:
    """
    Read the current template version from .template_version.json.

    Returns:
        Version string (e.g., "2.0.4") or "unknown"
    """
    try:
        if not TEMPLATE_VERSION_FILE.exists():
            return "unknown"

        data = json_loads(TEMPLATE_VERSION_FILE.read_text(encoding="utf-8"))
        return data.get("version", "unknown")
    except Exception:
        return "unknown"


def _get_last_rollover_info(central_stats: Dict) -> Dict[str, str]:
    """
    Build last_rollover info from central stats.

    Args:
        central_stats: Stats dict from _read_central_stats()

    Returns:
        Dict with 'date' (and optionally other info)
    """
    last_rollover_ts = central_stats.get("last_rollover", "")
    if last_rollover_ts:
        # Extract date portion from ISO timestamp
        try:
            dt = datetime.fromisoformat(last_rollover_ts)
            return {"date": dt.strftime("%Y-%m-%d")}
        except (ValueError, TypeError):
            return {"date": last_rollover_ts}
    return {"date": "never"}


def _get_all_branch_paths() -> List[Path]:
    """
    Get paths for all active branches from AIPASS_REGISTRY.json.

    Returns:
        List of Path objects for all registered branches
    """
    try:
        if not AIPASS_REGISTRY.exists():
            return []

        registry = json_loads(AIPASS_REGISTRY.read_text(encoding="utf-8"))
        repo_root = _find_repo_root()
        paths = []
        for branch in registry.get("branches", []):
            raw_path = branch.get("path", "")
            branch_path = Path(raw_path)
            if not branch_path.is_absolute():
                branch_path = repo_root / raw_path
            if branch_path.exists():
                paths.append(branch_path)
        return paths
    except Exception:
        return []


# =============================================================================
# PUBLIC API
# =============================================================================

def build_memory_bank_section() -> Dict[str, Any]:
    """
    Build the memory_bank dashboard section data.

    Collects all stats and returns the section dict ready for write_section().

    Returns:
        Dict with total_vectors, collections_count, branches_near_rollover,
        last_rollover, template_version
    """
    central_stats = _read_central_stats()
    near_rollover = _find_branches_near_rollover()
    last_rollover = _get_last_rollover_info(central_stats)
    template_version = _get_template_version()
    collections_count = _get_collections_count()

    return {
        "managed_by": "memory_bank",
        "total_vectors": central_stats.get("total_vectors", 0),
        "collections_count": collections_count,
        "branches_near_rollover": near_rollover,
        "last_rollover": last_rollover,
        "template_version": template_version
    }


def _write_section_to_all_branches(section_name: str, section_data: Dict,
                                    branch_paths: List[Path]) -> int:
    """
    Write a dashboard section to multiple branches via a single subprocess.

    Uses one subprocess call for all branches to avoid spawning 29 processes.
    The subprocess imports devpulse write_section and iterates all paths.

    Args:
        section_name: Dashboard section key (e.g., "memory_bank")
        section_data: Section data dict to write
        branch_paths: List of branch root directory paths

    Returns:
        Number of branches successfully updated
    """
    try:
        from json import dumps as json_dumps

        # Single subprocess handles all branches in a loop
        # Write dashboard section as JSON directly to DASHBOARD.local.json
        script = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "data = json.loads(sys.stdin.read())\n"
            "section_name = data['section_name']\n"
            "section_data = data['section_data']\n"
            "ok = 0\n"
            "for bp in data['branch_paths']:\n"
            "    try:\n"
            "        dash = Path(bp) / 'DASHBOARD.local.json'\n"
            "        if dash.exists():\n"
            "            d = json.loads(dash.read_text())\n"
            "            d[section_name] = section_data\n"
            "            dash.write_text(json.dumps(d, indent=2))\n"
            "            ok += 1\n"
            "    except Exception:\n"
            "        continue\n"
            "print(ok)\n"
        )

        input_data = json_dumps({
            "section_name": section_name,
            "section_data": section_data,
            "branch_paths": [str(p) for p in branch_paths]
        })

        result = subprocess.run(
            [sys.executable, "-c", script],
            input=input_data,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
        return 0
    except Exception:
        return 0


def push_memory_bank_dashboard() -> bool:
    """
    Push the memory_bank section to ALL branch dashboards.

    This is the main entry point called after rollover, pool processing,
    and plans processing. Memory Bank data is global so all branches
    benefit from seeing system memory health.

    Uses a single subprocess to call devpulse write_section() for all
    branches, avoiding cross-package handler imports. Dashboard write
    failures are silent - this is a best-effort operation that must not
    break the calling workflow.

    Returns:
        True if at least one dashboard was updated, False on total failure
    """
    try:
        # Build the section data once
        section_data = build_memory_bank_section()

        # Push to all branch dashboards via single subprocess
        branch_paths = _get_all_branch_paths()
        success_count = _write_section_to_all_branches(
            "memory_bank", section_data, branch_paths
        )

        log_operation("dashboard_push", {"branches_updated": success_count, "success": success_count > 0})

        return success_count > 0

    except Exception:
        return False


# =============================================================================
# CLI ENTRY POINT (for testing)
# =============================================================================

if __name__ == "__main__":
    import json

    print("Building memory_bank dashboard section...")
    section = build_memory_bank_section()
    print(json.dumps(section, indent=2))

    print()
    print("Pushing to all branch dashboards...")
    result = push_memory_bank_dashboard()
    print(f"Result: {'success' if result else 'failed'}")
