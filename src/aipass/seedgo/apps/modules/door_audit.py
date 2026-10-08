# =================== AIPass ====================
# Name: door_audit.py
# Description: Door: seedgo's branch audit, bypass rules and context ratchets, for the CI audit script (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Door for apps/handlers/audit/branch_audit.py, bypass/bypass_handler.py and context_standards/: the CI audit gate."""

from aipass.seedgo.apps.handlers.audit.branch_audit import audit_branch
from aipass.seedgo.apps.handlers.bypass.bypass_handler import load_bypass_rules
from aipass.seedgo.apps.handlers.context_standards import name_ratchet, startup_ratchet

__all__ = ["audit_branch", "load_bypass_rules", "name_ratchet", "startup_ratchet"]
