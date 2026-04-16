# =================== AIPass ====================
# Name: build_registry_entry.py
# Description: Registry Entry Builder
# Version: 0.1.0
# Created: 2025-11-15
# Modified: 2025-11-15
# =============================================

"""
Registry Entry Builder

Constructs registry entry dictionaries for new plans.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

from aipass.flow.apps.handlers.json import json_handler


def build_plan_registry_entry(
    plan_num: int, target_dir: Path, relative_location: str, subject: str, plan_file: Path, template_type: str
) -> Dict[str, Any]:
    """
    Build registry entry for new plan

    Constructs a complete registry entry dictionary with all
    required metadata for a newly created plan.

    Args:
        plan_num: Plan number (e.g., 1, 42, 101)
        target_dir: Absolute path to plan directory
        relative_location: Relative path string from calculate_relative_location()
        subject: Plan subject/title
        plan_file: Full path to plan file
        template_type: Template type (e.g., "default", "master")

    Returns:
        Dictionary with registry entry structure:
        {
            "location": str (absolute path),
            "relative_path": str,
            "created": str (ISO timestamp in UTC),
            "subject": str,
            "status": "open",
            "file_path": str (absolute path),
            "template_type": str
        }

    Example:
        >>> entry = build_plan_registry_entry(
        ...     1,
        ...     Path("/repo/src/aipass/flow"),
        ...     "flow",
        ...     "My task",
        ...     Path("/repo/src/aipass/flow/PLAN0001.md"),
        ...     "default"
        ... )
        >>> entry["status"]
        "open"
    """
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
