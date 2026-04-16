# =================== AIPass ====================
# Name: status.py
# Description: Dispatch Status Handler
# Version: 1.0.0
# Created: 2026-02-02
# Modified: 2026-02-02
# =============================================

"""
Dispatch Status Handler

Handles dispatch log storage and status checking.
Independent handler - no module dependencies.
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional

from aipass.prax.apps.modules.logger import system_logger as logger
from aipass.ai_mail.apps.handlers.json import json_handler

# Dispatch log location (package-relative)
_AI_MAIL_DIR = Path(__file__).resolve().parents[3]  # ai_mail/
DISPATCH_LOG_FILE = _AI_MAIL_DIR / ".ai_mail.local" / "dispatch_log.json"


def load_dispatch_log() -> List[Dict[str, Any]]:
    """Load dispatch log from JSON file"""
    if not DISPATCH_LOG_FILE.exists():
        return []

    try:
        with open(DISPATCH_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("dispatches", [])
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("[status] Failed to load dispatch log: %s", e)
        return []


def save_dispatch_log(dispatches: List[Dict[str, Any]]) -> bool:
    """Save dispatch log to JSON file"""
    try:
        # Ensure parent directory exists
        DISPATCH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Keep last 50 dispatches
        dispatches = dispatches[-50:]

        data = {"last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "dispatches": dispatches}

        with open(DISPATCH_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except IOError as e:
        logger.warning("[status] Failed to save dispatch log: %s", e)
        return False


def log_dispatch(branch: str, pid: Optional[int], status: str, error_msg: Optional[str] = None) -> bool:
    """
    Log a dispatch event.

    Args:
        branch: Target branch email (e.g., @flow)
        pid: Process ID if successful
        status: 'spawned' or 'failed'
        error_msg: Error message if failed

    Returns:
        True if logged successfully
    """
    json_handler.log_operation("log_dispatch", {"branch": branch, "status": status})

    dispatches = load_dispatch_log()

    entry: Dict[str, Any] = {
        "branch": branch,
        "pid": pid,
        "status": status,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    if error_msg:
        entry["error"] = error_msg

    dispatches.append(entry)
    return save_dispatch_log(dispatches)


def check_pid_status(pid: int) -> str:
    """
    Check if a PID is still running.

    Returns:
        'RUNNING', 'COMPLETED', or 'UNKNOWN'
    """
    try:
        result = subprocess.run(["ps", "-p", str(pid)], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "RUNNING"
        else:
            return "COMPLETED"
    except (subprocess.SubprocessError, OSError) as e:
        logger.warning("[status] Failed to check PID %s: %s", pid, e)
        return "UNKNOWN"


def calculate_age(timestamp_str: str) -> str:
    """Calculate human-readable age from timestamp"""
    if not timestamp_str:
        return "unknown"

    try:
        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        delta = now - timestamp

        total_seconds = int(delta.total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}s ago"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes}m ago"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours}h ago"
        else:
            days = total_seconds // 86400
            return f"{days}d ago"
    except ValueError as e:
        logger.warning("[status] Failed to parse timestamp '%s': %s", timestamp_str, e)
        return "unknown"
