# =================== AIPass ====================
# Name: door_trinity.py
# Description: Door: seedgo's trinity check and meta-line renderer, published for memory's trinity push (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Door for apps/handlers/aipass_standards/trinity_check.py and trinity_groups.py: the .trinity/ standard."""

from aipass.seedgo.apps.handlers.aipass_standards.trinity_check import check_branch
from aipass.seedgo.apps.handlers.aipass_standards.trinity_groups import expected_meta_line

__all__ = ["check_branch", "expected_meta_line"]
