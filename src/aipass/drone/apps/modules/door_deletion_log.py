# =================== AIPass ====================
# Name: door_deletion_log.py
# Description: Door: drone's deletion record, for another branch's removals and the hooks rm gate's refusals
# Version: 1.1.0
# Created: 2026-10-22
# Modified: 2026-11-15
# =============================================

"""Door for apps/handlers/deletion_log.py: one row in the fleet deletion trail, beside drone rm's."""

from aipass.drone.apps.handlers.deletion_log import record_foreign_deletion as record_deletion
from aipass.drone.apps.handlers.deletion_log import record_gate_refusal

__all__ = ["record_deletion", "record_gate_refusal"]
