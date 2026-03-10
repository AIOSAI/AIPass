# =================== AIPass ====================
# Name: reader.py
# Description: Central file reader — scans .ai_central/*.central.json
# Version: 1.0.0
# Created: 2026-03-10
# Modified: 2026-03-10
# =============================================

"""
Central File Reader

Reads all .ai_central/*.central.json files from the repo root
and returns a dict keyed by service name.

Used by dashboard/refresh.py to populate branch dashboards.
"""

import json
from pathlib import Path
from typing import Dict

from aipass.prax.apps.handlers.config.load import _find_repo_root


def read_all_centrals() -> Dict:
    """
    Read all .central.json files from .ai_central/ at repo root.

    Returns:
        Dict keyed by service name (e.g. 'ai_mail', 'plans', 'devpulse').
        Each value is the parsed JSON content of the central file.
        Returns empty dict if directory doesn't exist or has no files.
    """
    repo_root = _find_repo_root()
    central_dir = repo_root / ".ai_central"

    if not central_dir.is_dir():
        return {}

    centrals = {}
    for central_file in central_dir.glob("*.central.json"):
        try:
            data = json.loads(central_file.read_text(encoding="utf-8"))
            # Key by service name: AI_MAIL.central.json -> ai_mail
            service_name = central_file.name.replace(".central.json", "").lower()
            centrals[service_name] = data
        except (json.JSONDecodeError, OSError):
            continue

    return centrals
