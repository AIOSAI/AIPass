# =================== AIPass ====================
# Name: build_registry_entry.py
# Description: Registry Entry Builder
# Version: 0.1.0
# Created: 2025-11-15
# Modified: 2026-10-17
# =============================================

"""Registry Entry Builder

Constructs registry entry dictionaries for new plans.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from aipass.flow.apps.handlers.json import json_handler


def build_plan_registry_entry(
    plan_num: int, target_dir: Path, relative_location: str, subject: str, plan_file: Path, template_type: str
) -> Dict[str, Any]:
    """Build registry entry for new plan"""
    entry = {
        "location": str(target_dir),
        "relative_path": relative_location,
        "created": datetime.now(timezone.utc).isoformat(),
        "subject": subject,
        "status": "open",
        "file_path": str(plan_file),
        "template_type": template_type,
    }
    json_handler.log_operation(
        "registry_entry_built", {"plan_num": plan_num, "subject": subject, "location": relative_location}
    )
    return entry
