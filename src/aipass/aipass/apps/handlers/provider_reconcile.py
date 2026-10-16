# =================== AIPass ====================
# Name: provider_reconcile.py
# Description: Detect and fix stale rules in provider settings
# Version: 1.2.0
# Created: 2026-06-05
# Modified: 2026-10-15
# =============================================

"""provider_reconcile — detect and fix stale rules in ~/.claude/settings.json.

The fix backs the file up and leaves a receipt through ``settings_backup`` (door
``reconcile-stale-deny``, FPLAN-0645); a failed backup raises and nothing is written.
``plan_stale_deny`` computes the removal without writing, so the doctor can show it
and ask first (FPLAN-0646).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Optional

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.handlers.provider_wire import SettingsPlan, apply_settings_plan
from aipass.aipass.apps.handlers.settings_backup import DOOR_RECONCILE_STALE_DENY

_MODULE_NAME = "provider_reconcile"

_STALE_RM_DENY_RULES = frozenset({"Bash(rm -rf*)", "Bash(rm -r *)"})

GLYPH_PASS = "[green]✓[/green]"
GLYPH_WARN = "[yellow]![/yellow]"


def plan_stale_deny(settings_path: Optional[Path] = None, base: Optional[dict] = None) -> Optional[SettingsPlan]:
    """The stale rm deny rules a fix would remove, computed without writing; None when there are none.

    *base* is the settings as another plan would leave them (the doctor chains the
    wire plan first, so this removal lands on top of it); default: the file as it is.
    *settings_path* defaults to the personal settings file (the seam is for the test).
    """
    if settings_path is None:
        settings_path = Path.home() / ".claude" / "settings.json"
    if base is None:
        if not settings_path.exists():
            return None
        base = json_handler.read_json(settings_path)
        if base is None:
            return None
    deny = base.get("permissions", {}).get("deny", [])
    stale = [r for r in deny if r in _STALE_RM_DENY_RULES]
    if not stale:
        return None
    after = copy.deepcopy(base)
    after.setdefault("permissions", {})["deny"] = [r for r in deny if r not in _STALE_RM_DENY_RULES]
    return SettingsPlan(
        settings_path=settings_path,
        before=copy.deepcopy(base),
        after=after,
        actions=[f"Removed stale deny rules: {', '.join(stale)}"],
        planned=[f"Remove deny rule {r}" for r in stale],
        notes=[],
        door=DOOR_RECONCILE_STALE_DENY,
        updated_line="Updated ~/.claude/settings.json (stale deny rules removed)",
    )


def reconcile_stale_deny(fix: bool = False) -> list:
    """Detect and optionally remove stale rm deny rules from provider settings.

    Returns list of (label, glyph, detail, remediation) tuples matching
    doctor.CheckResult shape — imported as tuples to avoid circular import.
    With *fix*, the removal is backed up first and the row's detail names the
    backup and the receipt; ``SettingsBackupError`` propagates unwritten.
    """
    results: list = []
    settings_path = Path.home() / ".claude" / "settings.json"

    if not settings_path.exists():
        json_handler.log_operation(
            "reconcile_stale_deny",
            data={"fix": fix, "skipped": "no settings file"},
            module_name=_MODULE_NAME,
        )
        return results

    data = json_handler.read_json(settings_path)
    if data is None:
        json_handler.log_operation(
            "reconcile_stale_deny",
            data={"fix": fix, "skipped": "could not load settings"},
            module_name=_MODULE_NAME,
        )
        return results

    deny = data.get("permissions", {}).get("deny", [])
    stale = [r for r in deny if r in _STALE_RM_DENY_RULES]
    plan = plan_stale_deny(settings_path, base=data)

    if plan is None:
        results.append(("rm deny migration", GLYPH_PASS, "no stale rules", ""))
    elif fix:
        written = apply_settings_plan(plan)
        trail = "; ".join(a for a in written if a.startswith(("Backed up", "Receipt:")))
        detail = f"removed: {', '.join(stale)} — {trail}"
        results.append(("rm deny migration", GLYPH_PASS, detail, ""))
        logger.info("[doctor] removed stale deny rules: %s", stale)
    else:
        found = ", ".join(stale)
        results.append(
            (
                "rm deny migration",
                GLYPH_WARN,
                f"stale rules: {found}",
                "Run aipass doctor --fix to remove (rm_gate + drone rm replace these)",
            )
        )

    json_handler.log_operation(
        "reconcile_stale_deny",
        data={"fix": fix, "stale_found": len(stale)},
        module_name=_MODULE_NAME,
    )
    return results
