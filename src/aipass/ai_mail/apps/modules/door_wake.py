# =================== AIPass ====================
# Name: door_wake.py
# Description: Door: ai_mail's wake path, wake blocklist and transcript names, published for daemon, trigger and readers
# Version: 1.1.0
# Created: 2026-10-07
# Modified: 2026-11-15
# =============================================

"""Door for apps/handlers/dispatch/wake.py: the one wake path, its blocklist check and the wake's transcript names."""

from aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor import TRANSCRIPT_NAMES
from aipass.ai_mail.apps.handlers.dispatch.wake import is_wake_blocked, wake_branch

__all__ = ["wake_branch", "is_wake_blocked", "TRANSCRIPT_NAMES"]
