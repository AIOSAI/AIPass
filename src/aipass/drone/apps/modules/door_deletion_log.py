# =================== AIPass ====================
# Name: door_deletion_log.py
# Description: Door: drone's deletion record, for another branch's removals (spawn retire receipts)
# Version: 1.0.0
# Created: 2026-10-22
# Modified: 2026-10-22
# =============================================

"""Door for apps/handlers/deletion_log.py: one row in the fleet deletion trail, beside drone rm's."""

from aipass.drone.apps.handlers.deletion_log import record_foreign_deletion as record_deletion

__all__ = ["record_deletion"]
