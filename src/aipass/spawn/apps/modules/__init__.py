# =================== AIPass ====================
# Name: __init__.py
# Description: Modules gateway — the public door other branches import through
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Spawn's modules package — the gateway other branches import through.

``apps/handlers/`` is internal to this branch: its ``__init__`` refuses
cross-branch imports, and its refusal message points the caller here. This file
is what that message points AT for the citizen-class registry.

Exported for @seedgo's architecture check (DPLAN-0319 wave 3, FPLAN-0454), which
until now carried a drift-pinned MIRROR of the class table. A mirror makes the
auditor a fleet-wide single point of failure the moment spawn renames a class —
spawn's registry has to be the one source, so seedgo reads it here:

    from aipass.spawn.apps.modules import get_template_dir, refuse_legacy_class

``get_template_dir`` already refuses forbidden ("admin"), retired
("aipass_framework"/"project_agent"/"builder") and unknown values by name, so a
caller that just wants "resolve, or tell me why not" needs the one function and
a ``try/except ValueError``. ``refuse_legacy_class`` is the separate lane for
callers that must distinguish "this passport has not been migrated yet" from a
hard error — it returns "" for everything that is not a retired name.

These are RE-EXPORTS, never reimplementations. A gateway that drifts from its
handler is the same failure the mirror was, one layer closer in — pinned by
identity assertions in tests/test_modules_gateway.py.
"""

from aipass.spawn.apps.handlers.class_registry import (
    get_template_dir as get_template_dir,
    refuse_legacy_class as refuse_legacy_class,
)

__all__ = ["get_template_dir", "refuse_legacy_class"]
