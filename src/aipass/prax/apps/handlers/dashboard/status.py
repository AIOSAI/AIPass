# =================== AIPass ====================
# Name: status.py
# Description: Dashboard Status Calculation Handler
# Version: 0.2.0
# Created: 2026-02-25
# Modified: 2026-03-09
# =============================================

"""
Dashboard Status Handler

Handles status calculations and branch path resolution.
All business logic for dashboard status operations.
"""

import json
from pathlib import Path
from typing import Dict, List

from aipass.prax.apps.handlers.json import json_handler


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains AIPASS_REGISTRY.json)."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "AIPASS_REGISTRY.json").exists():
            return parent
    return Path.cwd()


AIPASS_REGISTRY = _find_repo_root() / "AIPASS_REGISTRY.json"


def calculate_quick_status(sections: Dict) -> Dict:
    """
    Calculate quick status from live section data.

    Reads directly from section fields pushed by each service.
    bulletin_board is dropped (FPLAN-0373); commons mentions added.

    Args:
        sections: All dashboard sections

    Returns:
        Quick status dict with summary data
    """
    ai_mail = sections.get("ai_mail", {})
    flow = sections.get("flow", {})
    commons = sections.get("commons_activity", {})

    # v2 schema: read "new" first, fall back to "unread" for backward compat
    new_mail = ai_mail.get("new", ai_mail.get("unread", 0))
    opened_mail = ai_mail.get("opened", 0)
    active_plans = flow.get("active_plans", 0)
    mentions = commons.get("mentions", 0)

    # Action required if new mail, active plans, or commons mentions
    action_required = new_mail > 0 or active_plans > 0 or mentions > 0

    summary_parts = []
    if new_mail:
        summary_parts.append(f"{new_mail} new emails")
    if opened_mail:
        summary_parts.append(f"{opened_mail} opened")
    if active_plans:
        summary_parts.append(f"{active_plans} active plans")
    if mentions:
        summary_parts.append(f"{mentions} mentions")

    result = {
        "new_mail": new_mail,
        "opened_mail": opened_mail,
        "active_plans": active_plans,
        "commons_mentions": mentions,
        "action_required": action_required,
        "summary": ", ".join(summary_parts) if summary_parts else "All clear",
    }

    json_handler.log_operation(
        "status_calculated",
        {
            "action_required": action_required,
            "new_mail": new_mail,
            "active_plans": active_plans,
        },
    )

    return result


def get_branch_paths() -> List[Path]:
    """
    Get all branch paths from registry

    Returns:
        List of branch paths

    Raises:
        FileNotFoundError: If AIPASS_REGISTRY.json doesn't exist
        json.JSONDecodeError: If registry is corrupted
    """
    if not AIPASS_REGISTRY.exists():
        raise FileNotFoundError(f"AIPASS_REGISTRY.json not found: {AIPASS_REGISTRY}")

    repo_root = _find_repo_root()
    data = json.loads(AIPASS_REGISTRY.read_text())
    paths = []
    for b in data.get("branches", []):
        raw = Path(b.get("path", ""))
        paths.append(raw if raw.is_absolute() else repo_root / raw)
    return paths


def resolve_branch_path(branch_ref: str) -> Path:
    """
    Resolve @branch reference to filesystem path via AIPASS_REGISTRY.json.

    Handler-layer function: performs file I/O to read registry and
    resolve branch name to its directory path.

    Args:
        branch_ref: Branch reference like "@flow" or "@vera"

    Returns:
        Path to the branch directory

    Raises:
        FileNotFoundError: If registry missing or branch not found
    """
    name = branch_ref.lstrip("@").upper()

    if not AIPASS_REGISTRY.exists():
        raise FileNotFoundError("AIPASS_REGISTRY.json not found")

    repo_root = _find_repo_root()
    data = json.loads(AIPASS_REGISTRY.read_text())
    for branch in data.get("branches", []):
        if branch.get("name", "").upper() == name:
            raw = Path(branch["path"])
            path = raw if raw.is_absolute() else repo_root / raw
            if path.exists():
                return path
            raise FileNotFoundError(f"Branch path does not exist: {path}")

    raise FileNotFoundError(f"Branch '{name}' not found in registry")
