# =================== AIPass ====================
# Name: update_local.py
# Description: Update Dashboard Local Handler
# Version: 2.1.0
# Created: 2025-11-21
# Modified: 2026-11-15
# =============================================

"""
Update Dashboard Local Handler
"""

from pathlib import Path
from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard
from aipass.flow.apps.handlers.json import json_handler

_PKG_ROOT = Path(__file__).resolve().parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"


def update_dashboard_local() -> bool | None:
    """
    Refresh Flow's own dashboard card through the shared section writer.

    Returns True if written, None if Flow has no dashboard (never created here), False if the write failed.
    """
    result = push_flow_to_branch_dashboard(FLOW_ROOT)
    json_handler.log_operation("dashboard_local_updated", {"branch": FLOW_ROOT.name, "success": result})
    return result
