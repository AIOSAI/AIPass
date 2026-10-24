# =================== AIPass ====================
# Name: dispatch_section.py
# Description: Dispatch status section builder for devpulse dashboard
# Version: 1.1.0
# Created: 2026-05-16
# Modified: 2026-10-23
# =============================================

"""Dispatch section builder for devpulse dashboard plugin."""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List

from aipass.prax.apps.modules.dashboard import get_branch_paths, write_section
from aipass.prax.apps.modules.logger import system_logger as logger


def _pid_alive(pid: object) -> bool:
    """Whether the lock's holder still runs; unknown counts as alive so a live dispatch never vanishes."""
    if not isinstance(pid, int) or pid <= 0:
        return True
    # os.kill on Windows terminates instead of probing.
    if sys.platform == "win32":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _read_lock(lock_path: Path) -> Dict:
    """Read ai_mail's dispatch lock ({pid, timestamp, branch}); {} once its holder is dead."""
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        # ai_mail holds an unparseable lock as mid-write, so it still counts.
        logger.warning("Failed to read dispatch lock %s: %s", lock_path, e)
        return {"pid": None, "timestamp": ""}
    if not isinstance(data, dict):
        return {"pid": None, "timestamp": ""}
    if not _pid_alive(data.get("pid")):
        return {}
    return {"pid": data.get("pid"), "timestamp": data.get("timestamp", "")}


def build_dispatch_section(branch_path: Path) -> bool:
    """Build dispatch section data and write to dashboard."""
    agents_active: List[str] = []
    details: Dict[str, Dict] = {}

    for path in get_branch_paths():
        lock_path = path / ".ai_mail.local" / ".dispatch.lock"
        if not lock_path.exists():
            continue
        lock = _read_lock(lock_path)
        if lock:
            agents_active.append(path.name)
            details[path.name] = lock

    section_data: Dict = {
        "managed_by": "devpulse",
        "agents_active": agents_active,
        "agents_active_count": len(agents_active),
        "details": details,
    }

    return write_section(branch_path, "dispatch", section_data)
