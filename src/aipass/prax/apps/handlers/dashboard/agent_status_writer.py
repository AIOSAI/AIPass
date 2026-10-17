# =================== AIPass ====================
# Name: agent_status_writer.py
# Description: Agent Status Dashboard Write-Through
# Version: 0.2.0
# Created: 2026-02-25
# Modified: 2026-10-17
# =============================================

"""
Agent Status Dashboard Write-Through Handler

Reads {branch}/ai_mail.local/.dispatch.lock (JSON: pid, timestamp, branch), checks
/proc/{pid}/cmdline, and pushes one system-wide section to ALL branch dashboards.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from aipass.prax.apps.modules.logger import get_direct_logger
from aipass.prax.apps.handlers.json import json_handler
from aipass.prax.apps.handlers.repo_root import find_repo_root

logger = get_direct_logger()


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root, never reading the cwd."""
    return find_repo_root(Path(__file__))


def _get_aipass_registry() -> Path:
    """Lazily resolve AIPASS_REGISTRY.json path."""
    return _find_repo_root() / "AIPASS_REGISTRY.json"


STALE_THRESHOLD_MINUTES = 120

# Only Linux has a proc filesystem to read; elsewhere a PID cannot be checked.
PROC_ROOT: Optional[Path] = Path("/proc") if sys.platform == "linux" else None


def _get_all_branches() -> List[Dict[str, Any]]:
    """Load all branches from AIPASS_REGISTRY.json."""
    try:
        registry = _get_aipass_registry()
        if not registry.exists():
            return []

        repo_root = _find_repo_root()
        data = json.loads(registry.read_text(encoding="utf-8"))
        branches = []
        for branch in data.get("branches", []):
            # Rows are repo-relative (external projects register absolute ones); an
            # unjoined row resolves against the cwd. Same join as refresh.py and template_pusher.py.
            raw_path = Path(branch.get("path", ""))
            branch_path = raw_path if raw_path.is_absolute() else repo_root / raw_path
            if branch_path.exists():
                branches.append({"name": branch.get("name", ""), "path": branch_path})
        return branches
    except Exception as e:
        logger.warning("Failed to load AIPASS_REGISTRY.json: %s", e)
        return []


def _is_pid_alive(pid: int, proc_root: Optional[Path]) -> Optional[bool]:
    """Check if a process is still running by reading <proc_root>/<pid>/cmdline."""
    # None means nobody could check: a PID that cannot be checked is unchecked, never dead.
    if proc_root is None:
        return None
    try:
        cmdline_path = proc_root / str(pid) / "cmdline"
        if not cmdline_path.exists():
            return False
        cmdline = cmdline_path.read_bytes().decode("utf-8", errors="replace")
        return "claude" in cmdline.lower()
    except OSError as e:
        logger.warning("Failed to check PID %d status, so it is reported unchecked: %s", pid, e)
        return None


def _read_lock_file(lock_path: Path) -> Optional[Dict[str, Any]]:
    """Read a dispatch lock file."""
    # {} is no lock; None is an unreadable lock, which must not hide a dispatch as {} would.
    try:
        if not lock_path.exists():
            return {}
        return json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read lock file %s: %s", lock_path, e)
        return None


def _calculate_runtime_minutes(timestamp_str: str) -> float:
    """Calculate minutes elapsed since a timestamp."""
    try:
        started = datetime.fromisoformat(timestamp_str)
        elapsed = datetime.now() - started
        return elapsed.total_seconds() / 60.0
    except (ValueError, TypeError) as e:
        logger.warning("Failed to parse timestamp '%s': %s", timestamp_str, e)
        return 0.0


def _scan_active_agents(proc_root: Optional[Path]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Scan all branches for active dispatch agents."""
    active_agents: List[Dict[str, Any]] = []
    stale_agents: List[Dict[str, Any]] = []

    branches = _get_all_branches()

    for branch in branches:
        lock_path = branch["path"] / "ai_mail.local" / ".dispatch.lock"
        lock_data = _read_lock_file(lock_path)

        if lock_data is None:
            stale_agents.append({"branch": branch["name"], "status": "unreadable_lock", "pid_checked": False})
            continue
        if not lock_data:
            continue

        pid = lock_data.get("pid", 0)
        timestamp = lock_data.get("timestamp", "")
        runtime_minutes = _calculate_runtime_minutes(timestamp)

        alive = _is_pid_alive(pid, proc_root)
        if alive is False:
            stale_agents.append(
                {
                    "branch": branch["name"],
                    "pid": pid,
                    "started": timestamp,
                    "runtime_minutes": round(runtime_minutes, 1),
                    "status": "dead_process",
                    "pid_checked": True,
                }
            )
            continue

        agent_info = {
            "branch": branch["name"],
            "pid": pid,
            "started": timestamp,
            "runtime_minutes": round(runtime_minutes, 1),
            "pid_checked": alive is True,
        }

        if runtime_minutes > STALE_THRESHOLD_MINUTES:
            agent_info["status"] = "overtime"
            stale_agents.append(agent_info)
        else:
            if alive is None:
                agent_info["status"] = "unchecked"
            active_agents.append(agent_info)

    return active_agents, stale_agents


def build_agent_status_section(proc_root: Optional[Path] = PROC_ROOT) -> Dict[str, Any]:
    """Build the agent_status dashboard section data."""
    # proc_root is a parameter so tests hand in a proc tree rather than read this machine's.
    active_agents, stale_agents = _scan_active_agents(proc_root)

    return {
        "managed_by": "prax",
        "active_agents": active_agents,
        "agent_count": len(active_agents),
        "stale_agents": stale_agents,
        "last_updated": datetime.now().isoformat(),
    }


def _get_all_branch_paths() -> List[Path]:
    """Get paths for all active branches from AIPASS_REGISTRY.json."""
    return [b["path"] for b in _get_all_branches()]


def _write_section_to_all_branches(section_name: str, section_data: Dict, branch_paths: List[Path]) -> int:
    """Write a dashboard section to multiple branches via a single subprocess."""
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
    """Push the agent_status section to ALL branch dashboards."""
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


if __name__ == "__main__":
    print("Building agent_status dashboard section...")
    section = build_agent_status_section()
    print(json.dumps(section, indent=2))

    print()
    print("Pushing to all branch dashboards...")
    result = push_agent_status_dashboard()
    print(f"Result: {'success' if result else 'failed'}")
