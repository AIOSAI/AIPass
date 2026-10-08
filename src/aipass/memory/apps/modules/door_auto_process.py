# =================== AIPass ====================
# Name: door_auto_process.py
# Description: Door: memory's background auto-process launch for hooks' lifecycle auto_process (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/intake/auto_process.py: the detached pool and plans processing run."""

from aipass.memory.apps.handlers.intake.auto_process import spawn_background

__all__ = ["spawn_background"]
