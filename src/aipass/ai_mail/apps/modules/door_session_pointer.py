# =================== AIPass ====================
# Name: door_session_pointer.py
# Description: Door: ai_mail's durable resume-session pointer, published for hooks and the watchdog (DPLAN-0404)
# Version: 1.1.0
# Created: 2026-10-07
# Modified: 2026-10-26
# =============================================

"""Door for apps/handlers/dispatch/session_pointer.py: resume target, pointer, transcript dir, Codex thread file."""

from aipass.ai_mail.apps.handlers.dispatch.session_pointer import (
    CLAUDE,
    CODEX,
    codex_thread_file,
    mint_session_id,
    read_pointer,
    resolve_resume_target,
    transcript_dir,
    write_pointer,
)

__all__ = [
    "resolve_resume_target",
    "write_pointer",
    "read_pointer",
    "transcript_dir",
    "codex_thread_file",
    "mint_session_id",
    "CLAUDE",
    "CODEX",
]
