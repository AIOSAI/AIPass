# =================== AIPass ====================
# Name: provider_reconcile.py
# Description: Detect and fix stale rules in provider settings
# Version: 1.0.0
# Created: 2026-06-05
# Modified: 2026-06-05
# =============================================

"""provider_reconcile — detect and fix stale rules in ~/.claude/settings.json."""

from __future__ import annotations

from pathlib import Path

from aipass.prax import logger

from aipass.aipass.apps.handlers.json import json_handler

_MODULE_NAME = "provider_reconcile"

_STALE_RM_DENY_RULES = frozenset({"Bash(rm -rf*)", "Bash(rm -r *)"})

GLYPH_PASS = "[green]✓[/green]"
GLYPH_WARN = "[yellow]![/yellow]"


def reconcile_stale_deny(fix: bool = False) -> list:
    """Detect and optionally remove stale rm deny rules from provider settings.

    Returns list of (label, glyph, detail, remediation) tuples matching
    doctor.CheckResult shape — imported as tuples to avoid circular import.
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

    if not stale:
        results.append(("rm deny migration", GLYPH_PASS, "no stale rules", ""))
    elif fix:
        deny_cleaned = [r for r in deny if r not in _STALE_RM_DENY_RULES]
        data.setdefault("permissions", {})["deny"] = deny_cleaned
        json_handler.write_json(settings_path, data)
        removed = ", ".join(stale)
        results.append(("rm deny migration", GLYPH_PASS, f"removed: {removed}", ""))
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
