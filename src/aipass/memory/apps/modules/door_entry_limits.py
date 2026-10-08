# =================== AIPass ====================
# Name: door_entry_limits.py
# Description: Door: memory's entry limits and file budgets for hooks' edit gate and pre-compact prep (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/json/entry_limits.py: the caps, the closed entry shape and the file budgets."""

from aipass.memory.apps.handlers.json.entry_limits import (
    changed_entries,
    check_file_budget,
    fields_for,
    load_entry_limits,
)

__all__ = ["load_entry_limits", "check_file_budget", "changed_entries", "fields_for"]
