# =================== AIPass ====================
# Name: dispatch_section.py
# Description: Dispatch status section builder for devpulse dashboard
# Version: 1.0.0
# Created: 2026-05-16
# Modified: 2026-05-16
# =============================================

"""Dispatch section builder for devpulse dashboard plugin.

Scans all 12 AIPass branches for .dispatch.lock files to show
which agents are currently active. Writes to dashboard via write_section().
"""

import json
from pathlib import Path
from typing import Dict, List

from aipass.prax.apps.modules.dashboard import write_section
from aipass.prax.apps.modules.logger import system_logger as logger

BRANCH_NAMES: List[str] = [
    "ai_mail",
    "aipass",
    "api",
    "cli",
    "devpulse",
    "drone",
    "flow",
    "memory",
    "prax",
    "seedgo",
    "spawn",
    "trigger",
]


def _get_aipass_src(branch_path: Path) -> Path:
    """Resolve the src/aipass/ root from any branch path."""
    return branch_path.resolve().parent


def _read_lock(lock_path: Path) -> Dict:
    """Read dispatch lock file, return parsed data or empty dict."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return {
            "subject": data.get("subject", ""),
            "started": data.get("started", ""),
        }
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read dispatch lock %s: %s", lock_path, e)
        return {"subject": "unknown", "started": ""}


def build_dispatch_section(branch_path: Path) -> bool:
    """Build dispatch section data and write to dashboard.

    Scans all 13 branches for active dispatch locks.

    Args:
        branch_path: Path to devpulse branch root.

    Returns:
        True if write_section succeeded, False otherwise.
    """
    aipass_src = _get_aipass_src(branch_path)

    agents_active: List[str] = []
    details: Dict[str, Dict] = {}

    for name in BRANCH_NAMES:
        lock_path = aipass_src / name / ".ai_mail.local" / ".dispatch.lock"
        if lock_path.exists():
            agents_active.append(name)
            details[name] = _read_lock(lock_path)

    section_data: Dict = {
        "managed_by": "devpulse",
        "agents_active": agents_active,
        "agents_active_count": len(agents_active),
        "details": details,
    }

    return write_section(branch_path, "dispatch", section_data)
