# =================== AIPass ====================
# Name: door_wake.py
# Description: Door: ai_mail's wake path and wake blocklist, published for daemon and trigger (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/dispatch/wake.py: the one wake path and its blocklist check."""

from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked, wake_branch

__all__ = ["wake_branch", "is_wake_blocked"]
