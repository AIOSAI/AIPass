# =================== AIPass ====================
# Name: door_verified_caller.py
# Description: Door: ai_mail's verified-caller rail and admin verdict, published for drone and hooks (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/users/verified_caller.py: the verified-caller rail and the admin verdict."""

from aipass.ai_mail.apps.handlers.users.verified_caller import is_verified_admin_caller, resolve_verified_caller

__all__ = ["is_verified_admin_caller", "resolve_verified_caller"]
