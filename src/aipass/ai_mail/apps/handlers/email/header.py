# =================== AIPass ====================
# Name: header.py
# Description: Email Header Handler
# Version: 1.2.1
# Created: 2026-02-04
# Modified: 2026-10-17
# =============================================

"""
Email Header Handler

Keep every import BELOW this string: after an import it is not __doc__.
"""

from aipass.ai_mail.apps.handlers.json import json_handler

DISPATCH_HEADER = """⚡ DISPATCH TASK - READ THIS FIRST ⚡

BEFORE YOU REPLY, YOU MUST:
1. ✅ Complete the task below
2. ✅ UPDATE YOUR MEMORIES (.local.json) - this is NOT optional
3. ✅ Then reply with your completion summary

⚠️ Run sub-agents SYNCHRONOUSLY (run_in_background: false). This is a headless
session: background tasks are killed shortly after your turn ends and you are
never re-invoked — finish all work and send your reply BEFORE ending your turn.

⚠️ Found work in the tree you cannot explain? REPORT it — never invent an author.
Unexplained changes are evidence: state what you found, attribute it to no one.

Your memories are your presence. Skip the update = you never existed.

---
"""

NO_MEMORY_SAVE_HEADER = """⚡ DISPATCH TASK - READ THIS FIRST ⚡

MEMORY UPDATE: OPTIONAL — This dispatch was sent with --no-memory-save. Do NOT log this task in
your memory files (.local.json). Execute the task and reply, but leave no trace in your memories.

BEFORE YOU REPLY, YOU MUST:
1. ✅ Complete the task below
2. ✅ Then reply with your completion summary

⚠️ Run sub-agents SYNCHRONOUSLY (run_in_background: false). This is a headless
session: background tasks are killed shortly after your turn ends and you are
never re-invoked — finish all work and send your reply BEFORE ending your turn.

⚠️ Found work in the tree you cannot explain? REPORT it — never invent an author.
Unexplained changes are evidence: state what you found, attribute it to no one.

---
"""


def get_dispatch_header(no_memory_save: bool = False) -> str:
    """Get the dispatch email header."""
    if no_memory_save:
        return NO_MEMORY_SAVE_HEADER
    return DISPATCH_HEADER


def prepend_dispatch_header(message: str, no_memory_save: bool = False) -> str:
    """Prepend dispatch header to email message."""
    json_handler.log_operation("prepend_dispatch_header", {"no_memory_save": no_memory_save})
    return get_dispatch_header(no_memory_save=no_memory_save) + message


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("EMAIL HEADER HANDLER")
    print("=" * 70)
    print("\nPURPOSE:")
    print("  Generates header for dispatch emails (critical reminders)")
    print()
    print("FUNCTIONS PROVIDED:")
    print("  - get_dispatch_header() -> str")
    print("  - prepend_dispatch_header(message) -> str")
    print()
    print("HEADER CONTENT:")
    print(DISPATCH_HEADER)
    print()
    print("HANDLER CHARACTERISTICS:")
    print("  ✓ Independent - no module dependencies")
    print("  ✓ Can import Prax (service provider)")
    print("  ✓ Pure business logic")
    print("  ✗ CANNOT import parent modules")
    print()
    print("USAGE FROM MODULES:")
    print("  from ai_mail.apps.handlers.email.header import prepend_dispatch_header")
    print()
    print("=" * 70 + "\n")
