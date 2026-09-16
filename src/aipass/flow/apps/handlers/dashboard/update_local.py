# =================== AIPass ====================
# Name: update_local.py
# Description: Update Dashboard Local Handler
# Version: 2.0.0
# Created: 2025-11-21
# Modified: 2026-09-15
# =============================================

"""
Update Dashboard Local Handler

Refreshes Flow's OWN DASHBOARD.local.json after a plan operation, by calling
the same writer every other branch's card goes through.

Why this is a delegation (2026-09-15, DPLAN-0347 / FPLAN-0593 Phase 2):

Until now this handler wrote its own top-level ``flow_plans`` key, outside
``sections``. The drift map measured what that cost:

- Nothing read it. A grep across ``src/`` found one writer (here) and no
  production consumer -- only this module's own tests.
- It flapped. @prax's refresh rebuilds the file from the template and drops
  unknown top-level keys, then the next plan operation re-added it. Measured on
  Flow's own dashboard 2026-09-15: absent at 16:56 after a refresh, back at
  23:58 after a plan op.
- ``sections`` is what the dashboard's preserve and budget logic can see, so a
  key beside it is invisible to both: never preserved, never measured.
- It carried the unbounded full active list -- the shape the 2026-08-16 ruling
  removed from the section precisely because a dashboard must not carry
  unbounded context.
- Its ``location`` filter was a substring match, so ``"flow" in location``
  also matched throwaway test directories whose names merely contain "flow",
  and published their plans as Flow's own.

The section writer already fixed every one of those: bounded window, exact
location match, subjects cut to the shared cap, whole-file budget warn. Flow's
own card is written by it on every plan operation anyway, so the top-level key
was a second, worse copy of a card that was already correct.

The one behaviour change: the section writer refuses to CREATE a dashboard that
does not exist (a directory with no dashboard is not a branch), where the old
code created one. ``drone @prax dashboard refresh @flow`` is the door that
mints it.

Usage:
    from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local

    success = update_dashboard_local()
    # Returns True on success, False on failure
"""

from aipass.flow.apps.handlers.dashboard.push_branch_dashboard import push_flow_to_branch_dashboard
from aipass.flow.apps.handlers.json import json_handler

# INFRASTRUCTURE IMPORT PATTERN
from aipass.flow.apps.handlers.repo_root import module_file

_PKG_ROOT = module_file(__file__).parents[4]
FLOW_ROOT = _PKG_ROOT / "flow"


# =============================================
# HANDLER FUNCTION
# =============================================


def update_dashboard_local() -> bool:
    """
    Refresh Flow's own dashboard card through the shared section writer.

    Returns:
        True if the card was written, False if Flow has no dashboard file or
        the write failed (the section writer logs the reason).

    Example:
        >>> from aipass.flow.apps.handlers.dashboard.update_local import update_dashboard_local
        >>> success = update_dashboard_local()
    """
    result = push_flow_to_branch_dashboard(FLOW_ROOT)
    json_handler.log_operation("dashboard_local_updated", {"branch": FLOW_ROOT.name, "success": result})
    return result
