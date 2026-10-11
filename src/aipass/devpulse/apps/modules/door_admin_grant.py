# =================== AIPass ====================
# Name: door_admin_grant.py
# Description: Door: devpulse's admin-grant verification, published for ai_mail's verified-caller rail (DPLAN-0404)
# Version: 1.1.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/owner/admin_grant.py: the one home of the 5-leg admin contract."""

from aipass.devpulse.apps.handlers.owner.admin_grant import compute_signature, verify_admin_grant

__all__ = ["verify_admin_grant", "compute_signature"]
