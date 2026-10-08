# =================== AIPass ====================
# Name: door_trail.py
# Description: Door: backup's operation audit trail, published for seedgo's os_walk_onerror test (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Door for apps/handlers/audit/trail.py: backup's JSONL operation audit trail."""

from aipass.backup.apps.handlers.audit.trail import log_operation

__all__ = ["log_operation"]
