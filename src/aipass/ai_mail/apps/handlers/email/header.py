# =================== AIPass ====================
# Name: header.py
# Description: Email Header Handler
# Version: 1.3.0
# Created: 2026-02-04
# Modified: 2026-10-28
# =============================================

"""
Email Header Handler

Keep every import BELOW this string: after an import it is not __doc__.
"""

from aipass.ai_mail.apps.handlers.json import json_handler

_TITLE = "⚡ DISPATCH TASK - READ THIS FIRST ⚡\n\n"

_WARNINGS = """⚠️ Run sub-agents in the FOREGROUND and wait for them to finish. This is a headless
session: background work is killed when your turn ends and you are never
re-invoked — finish all work and send your reply BEFORE ending your turn.

⚠️ Found work in the tree you cannot explain? REPORT it — never invent an author.
Unexplained changes are evidence: state what you found, attribute it to no one.

"""

DISPATCH_HEADER = (
    _TITLE
    + """BEFORE YOU REPLY, YOU MUST:
1. ✅ Complete the task below
2. ✅ UPDATE YOUR MEMORIES (.local.json) - this is NOT optional
3. ✅ Then reply with your completion summary

"""
    + _WARNINGS
    + "Your memories are your presence. Skip the update = you never existed.\n\n---\n"
)

NO_MEMORY_SAVE_HEADER = (
    _TITLE
    + """MEMORY UPDATE: OPTIONAL — This dispatch was sent with --no-memory-save. Do NOT log this task in
your memory files (.local.json). Execute the task and reply, but leave no trace in your memories.

BEFORE YOU REPLY, YOU MUST:
1. ✅ Complete the task below
2. ✅ Then reply with your completion summary

"""
    + _WARNINGS
    + "---\n"
)


def get_dispatch_header(no_memory_save: bool = False) -> str:
    """Get the dispatch email header."""
    if no_memory_save:
        return NO_MEMORY_SAVE_HEADER
    return DISPATCH_HEADER


def prepend_dispatch_header(message: str, no_memory_save: bool = False) -> str:
    """Prepend dispatch header to email message."""
    json_handler.log_operation("prepend_dispatch_header", {"no_memory_save": no_memory_save})
    return get_dispatch_header(no_memory_save=no_memory_save) + message
