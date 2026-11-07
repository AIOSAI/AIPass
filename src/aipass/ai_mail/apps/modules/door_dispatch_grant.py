# =================== AIPass ====================
# Name: door_dispatch_grant.py
# Description: Door: a dispatch's scoped write grant, the decision a gate reads for one write
# Version: 1.0.0
# Created: 2026-11-03
# Modified: 2026-11-03
# =============================================

"""Door for apps/handlers/dispatch/grant.py: granted() decides one write, open_grants() lists the open ones."""

from aipass.ai_mail.apps.handlers.dispatch.grant import GRANT_KEY, granted, open_grants

__all__ = ["granted", "open_grants", "GRANT_KEY"]
