# =================== AIPass ====================
# Name: door_session_pointer.py
# Description: Door: ai_mail's durable resume-session pointer, published for hooks (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/dispatch/session_pointer.py: the resume target, the pointer and the transcript dir."""

from aipass.ai_mail.apps.handlers.dispatch.session_pointer import (
    read_pointer,
    resolve_resume_target,
    transcript_dir,
    write_pointer,
)

__all__ = ["resolve_resume_target", "write_pointer", "read_pointer", "transcript_dir"]
