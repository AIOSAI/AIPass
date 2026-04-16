# =================== AIPass ====================
# Name: agent_status_writer.py
# Description: Agent Status Dashboard Write-Through
# Version: 0.1.0
# Created: 2026-02-25
# Modified: 2026-03-09
# =============================================

"""
Agent Status Dashboard Write-Through Handler

Pushes the 'agent_status' section to branch dashboards via prax write_section().
Scans dispatch lock files and /proc to detect active and stale agents, then pushes
to ALL branch dashboards (agent status is system-wide info).

Data sources:
  - Dispatch lock files: {branch}/ai_mail.local/.dispatch.lock (JSON: pid, timestamp, branch)
  - Process validation: /proc/{pid}/cmdline to confirm agent is still alive
  - Stale threshold: agents running > 120 minutes
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from aipass.prax.apps.modules.logger import get_direct_logger

logger = get_direct_logger()

from aipass.prax.apps.handlers.json import json_handler


# =============================================================================
# CONSTANTS
# =============================================================================


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


def _get_aipass_registry() -> Path:
    """Lazily resolve AIPASS_REGISTRY.json path."""
    return _find_repo_root() / "AIPASS_REGISTRY.json"


STALE_THRESHOLD_MINUTES = 120


# =============================================================================
# DATA COLLECTION
# =============================================================================


def _get_all_branches() -> List[Dict[str, Any]]:
    """
    Load all branches from AIPASS_REGISTRY.json.

    Returns:
        List of dicts with 'name' and 'path' keys
    """
    try:
        registry = _get_aipass_registry()
        if not registry.exists():
            return []

        data = json.loads(registry.read_text(encoding="utf-8"))
        branches = []
        for branch in data.get("branches", []):
            branch_path = Path(branch.get("path", ""))
            if branch_path.exists():
                branches.append({"name": branch.get("name", ""), "path": branch_path})
        return branches
    except Exception as e:
        logger.warning("Failed to load AIPASS_REGISTRY.json: %s", e)
        return []


def _is_pid_alive(pid: int) -> bool:
    """
    Check if a process is still running by reading /proc/{pid}/cmdline.

    Args:
        pid: Process ID to check

    Returns:
        True if process exists and looks like a claude agent
    """
    try:
        if sys.platform != "linux":
            return False
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if not cmdline_path.exists():
            return False
        cmdline = cmdline_path.read_bytes().decode("utf-8", errors="replace")
        return "claude" in cmdline.lower()
    except (PermissionError, OSError) as e:
        logger.warning("Failed to check PID %d status: %s", pid, e)
        return False


def _read_lock_file(lock_path: Path) -> Dict[str, Any]:
    """
    Read a dispatch lock file.

    Args:
        lock_path: Path to .dispatch.lock file

    Returns:
        Lock data dict with pid, timestamp, branch — or empty dict on failure
    """
    try:
        if not lock_path.exists():
            return {}
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read lock file %s: %s", lock_path, e)
        return {}


def _calculate_runtime_minutes(timestamp_str: str) -> float:
    """
    Calculate minutes elapsed since a timestamp.

    Args:
        timestamp_str: ISO format timestamp string

    Returns:
        Minutes elapsed, or 0.0 on parse failure
    """
    try:
        started = datetime.fromisoformat(timestamp_str)
        elapsed = datetime.now() - started
        return elapsed.total_seconds() / 60.0
    except (ValueError, TypeError) as e:
        logger.warning("Failed to parse timestamp '%s': %s", timestamp_str, e)
        return 0.0


def _scan_active_agents() -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Scan all branches for active dispatch agents.

    Reads .dispatch.lock files, validates PIDs against /proc, and
    classifies agents as active or stale based on runtime.

    Returns:
        Tuple of (active_agents, stale_agents) — each a list of dicts
    """
    active_agents: List[Dict[str, Any]] = []
    stale_agents: List[Dict[str, Any]] = []

    branches = _get_all_branches()

    for branch in branches:
        lock_path = branch["path"] / "ai_mail.local" / ".dispatch.lock"
        lock_data = _read_lock_file(lock_path)

        if not lock_data:
            continue

        pid = lock_data.get("pid", 0)
        timestamp = lock_data.get("timestamp", "")
        runtime_minutes = _calculate_runtime_minutes(timestamp)

        # Validate PID is still alive
        if not _is_pid_alive(pid):
            # Stale lock — process died without cleanup
            stale_agents.append(
                {
                    "branch": branch["name"],
                    "pid": pid,
                    "started": timestamp,
                    "runtime_minutes": round(runtime_minutes, 1),
                    "status": "dead_process",
                }
            )
            continue

        agent_info = {
            "branch": branch["name"],
            "pid": pid,
            "started": timestamp,
            "runtime_minutes": round(runtime_minutes, 1),
        }

        if runtime_minutes > STALE_THRESHOLD_MINUTES:
            agent_info["status"] = "overtime"
            stale_agents.append(agent_info)
        else:
            active_agents.append(agent_info)

    return active_agents, stale_agents


# =============================================================================
# PUBLIC API
# =============================================================================


def build_agent_status_section() -> Dict[str, Any]:
    """
    Build the agent_status dashboard section data.

    Scans for active dispatch agents and returns section dict ready for
    write_section().

    Returns:
        Dict with managed_by, active_agents, agent_count, stale_agents,
        last_updated
    """
    active_agents, stale_agents = _scan_active_agents()

    return {
        "managed_by": "prax",
        "active_agents": active_agents,
        "agent_count": len(active_agents),
        "stale_agents": stale_agents,
        "last_updated": datetime.now().isoformat(),
    }


def _get_all_branch_paths() -> List[Path]:
    """
    Get paths for all active branches from AIPASS_REGISTRY.json.

    Returns:
        List of Path objects for all registered branches
    """
    return [b["path"] for b in _get_all_branches()]


def _write_section_to_all_branches(section_name: str, section_data: Dict, branch_paths: List[Path]) -> int:
    """
    Write a dashboard section to multiple branches via a single subprocess.

    Uses one subprocess call for all branches to avoid spawning N processes.
    Pattern from memory/apps/handlers/dashboard_push.py.

    Args:
        section_name: Dashboard section key (e.g., "agent_status")
        section_data: Section data dict to write
        branch_paths: List of branch root directory paths

    Returns:
        Number of branches successfully updated
    """
    try:
        script = (
            "import sys, json\n"
            "from pathlib import Path\n"
            "from aipass.prax.apps.modules.dashboard import write_section\n"
            "data = json.loads(sys.stdin.read())\n"
            "section_name = data['section_name']\n"
            "section_data = data['section_data']\n"
            "ok = 0\n"
            "for bp in data['branch_paths']:\n"
            "    try:\n"
            "        if write_section(Path(bp), section_name, dict(section_data)):\n"
            "            ok += 1\n"
            "    except Exception:\n"
            "        continue\n"
            "print(ok)\n"
        )

        input_data = json.dumps(
            {"section_name": section_name, "section_data": section_data, "branch_paths": [str(p) for p in branch_paths]}
        )

        result = subprocess.run(
            [sys.executable, "-c", script], input=input_data, capture_output=True, text=True, timeout=60
        )

        if result.returncode == 0 and result.stdout.strip().isdigit():
            return int(result.stdout.strip())
        return 0
    except Exception as e:
        logger.error("Failed to write agent_status section to branches: %s", e)
        return 0


def push_agent_status_dashboard() -> bool:
    """
    Push the agent_status section to ALL branch dashboards.

    Main entry point. Scans for active/stale dispatch agents and pushes
    results to every branch dashboard. Agent status is system-wide info
    so all branches benefit from knowing what's running.

    Uses a single subprocess to call devpulse write_section() for all
    branches. Dashboard write failures are silent — best-effort operation.

    Returns:
        True if at least one dashboard was updated, False on total failure
    """
    try:
        section_data = build_agent_status_section()
        branch_paths = _get_all_branch_paths()

        if not branch_paths:
            return False

        success_count = _write_section_to_all_branches("agent_status", section_data, branch_paths)

        json_handler.log_operation(
            "agent_status_written",
            {
                "branches_targeted": len(branch_paths),
                "branches_updated": success_count,
                "active_agents": section_data.get("agent_count", 0),
                "stale_agents": len(section_data.get("stale_agents", [])),
            },
        )

        return success_count > 0

    except Exception as e:
        logger.error("Failed to push agent status dashboard: %s", e)
        return False


# =============================================================================
# CLI ENTRY POINT (for testing)
# =============================================================================

if __name__ == "__main__":
    print("Building agent_status dashboard section...")
    section = build_agent_status_section()
    print(json.dumps(section, indent=2))

    print()
    print("Pushing to all branch dashboards...")
    result = push_agent_status_dashboard()
    print(f"Result: {'success' if result else 'failed'}")
