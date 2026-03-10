# =================== AIPass ====================
# Name: dashboard.py
# Description: DPLAN Dashboard Push Handler
# Version: 2.0.0
# Created: 2026-02-25
# Modified: 2026-02-25
# =============================================

"""
Dashboard Handler - DPLAN Dashboard Integration

Computes enriched DPLAN summary data. The module layer injects
the write_section function to push to DASHBOARD.local.json (handler
independence pattern). Central push is handled directly here.
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, Callable

# NOTE: Handlers do NOT import Prax logger (per 3-tier standard)

from .registry import load_registry

# =============================================================================
# CONFIGURATION
# =============================================================================

# dashboard.py → dplan/ → handlers/ → apps/ → flow/ → aipass/
FLOW_ROOT = Path(__file__).resolve().parents[3]
AIPASS_ROOT = Path(__file__).resolve().parents[4]
DEVPULSE_ROOT = AIPASS_ROOT / "devpulse"
CENTRAL_FILE = DEVPULSE_ROOT / "DEVPULSE.central.json"


# =============================================================================
# HANDLER FUNCTIONS
# =============================================================================

def compute_dplan_summary(activity: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute enriched DPLAN summary from registry.

    Args:
        activity: Optional recent activity string
            (e.g. "DPLAN-036 created (dashboard_overhaul)")

    Returns:
        Dashboard section dict with managed_by, dplan_counts, recent_activity
    """
    registry = load_registry()
    plans = registry.get("plans", {})

    by_status: Dict[str, int] = {}

    for plan in plans.values():
        status = plan.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    # Derive recent_activity from registry if not provided
    if not activity:
        activity = _derive_recent_activity(plans)

    return {
        "managed_by": "devpulse",
        "dplan_counts": {
            "total": len(plans),
            "by_status": by_status
        },
        "recent_activity": activity
    }


def _derive_recent_activity(plans: Dict[str, Any]) -> str:
    """
    Derive a recent_activity string from the most recently updated plan.

    Args:
        plans: Registry plans dict

    Returns:
        Activity string like "DPLAN-036 updated (dashboard_overhaul)"
    """
    if not plans:
        return ""

    # Find plan with most recent last_updated timestamp
    most_recent = None
    most_recent_ts = ""

    for plan in plans.values():
        ts = plan.get("last_updated", "")
        if ts > most_recent_ts:
            most_recent_ts = ts
            most_recent = plan

    if most_recent:
        num = most_recent.get("number", 0)
        topic = most_recent.get("topic", "unknown")
        short_topic = topic[:30].replace(" ", "_").lower()
        status = most_recent.get("status", "unknown")
        return f"DPLAN-{num:03d} {status} ({short_topic})"

    return ""


def push_dplan_to_dashboard(
    summary: Dict[str, Any],
    write_fn: Optional[Callable] = None
) -> bool:
    """
    Update devpulse's own DASHBOARD.local.json.

    Uses injected write_fn (write_section from module layer) for handler
    independence. Falls back to direct JSON write if no write_fn provided.

    Args:
        summary: DPLAN section data from compute_dplan_summary()
        write_fn: Callable(branch_path, section_name, section_data) -> bool.
            Injected by module layer (write_section from dashboard operations).

    Returns:
        True if successful
    """
    if write_fn:
        return write_fn(DEVPULSE_ROOT, "devpulse", summary)

    # Fallback: direct write (backward compatibility)
    dashboard_file = DEVPULSE_ROOT / "DASHBOARD.local.json"
    if not dashboard_file.exists():
        return False

    try:
        with open(dashboard_file, 'r', encoding='utf-8') as f:
            dashboard = json.load(f)

        dashboard.setdefault("sections", {})
        summary["last_updated"] = datetime.now().isoformat()
        dashboard["sections"]["devpulse"] = summary
        dashboard["last_updated"] = datetime.now().isoformat()

        with open(dashboard_file, 'w', encoding='utf-8') as f:
            json.dump(dashboard, f, indent=2, ensure_ascii=False)

        return True
    except Exception:
        return False


def push_dplan_to_central(summary: Dict[str, Any]) -> bool:
    """
    Add DPLAN counts to DEVPULSE.central.json alongside branch summaries.

    Args:
        summary: DPLAN section data from compute_dplan_summary()

    Returns:
        True if successful
    """
    if not CENTRAL_FILE.exists():
        return False

    try:
        with open(CENTRAL_FILE, 'r', encoding='utf-8') as f:
            central = json.load(f)

        central["dplan_summary"] = summary
        central["last_updated"] = datetime.now().isoformat()

        with open(CENTRAL_FILE, 'w', encoding='utf-8') as f:
            json.dump(central, f, indent=2, ensure_ascii=False)

        return True
    except Exception:
        return False


def push_all(
    activity: Optional[str] = None,
    write_fn: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Compute DPLAN summary and push to both dashboard and central.

    Args:
        activity: Optional recent activity string for dashboard display
        write_fn: Optional write_section callable injected by module layer

    Returns:
        The computed summary dict
    """
    summary = compute_dplan_summary(activity=activity)
    push_dplan_to_dashboard(summary, write_fn=write_fn)
    push_dplan_to_central(summary)
    return summary
