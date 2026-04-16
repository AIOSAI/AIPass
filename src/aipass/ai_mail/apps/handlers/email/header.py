# =================== AIPass ====================
# Name: header.py
# Description: Email Header Handler
# Version: 1.0.0
# Created: 2026-02-04
# Modified: 2026-02-04
# =============================================


from aipass.ai_mail.apps.handlers.json import json_handler

"""
Email Header Handler

Generates and prepends headers to outgoing emails.
Critical dispatch header ensures agents see memory update reminder FIRST.
Independent handler - no module dependencies.
"""

# Header for dispatch emails - agents see this FIRST before the task
DISPATCH_HEADER = """⚡ DISPATCH TASK - READ THIS FIRST ⚡

BEFORE YOU REPLY, YOU MUST:
1. ✅ Complete the task below
2. ✅ UPDATE YOUR MEMORIES (.local.json) - this is NOT optional
3. ✅ Then reply with your completion summary

Your memories are your presence. Skip the update = you never existed.

---
"""

# Header override when --no-memory-save is set (private branch outbound)
NO_MEMORY_SAVE_HEADER = """⚡ DISPATCH TASK - READ THIS FIRST ⚡

MEMORY UPDATE: OPTIONAL — This dispatch was sent with --no-memory-save. Do NOT log this task in your memory files (.local.json). Execute the task and reply, but leave no trace in your memories.

BEFORE YOU REPLY, YOU MUST:
1. ✅ Complete the task below
2. ✅ Then reply with your completion summary

---
"""


def get_dispatch_header(no_memory_save: bool = False) -> str:
    """
    Get the dispatch email header.

    Args:
        no_memory_save: If True, return header with no-memory-save directive

    Returns:
        Dispatch header string for dispatch emails
    """
    if no_memory_save:
        return NO_MEMORY_SAVE_HEADER
    return DISPATCH_HEADER


def prepend_dispatch_header(message: str, no_memory_save: bool = False) -> str:
    """
    Prepend dispatch header to email message.

    Args:
        message: Original email message body
        no_memory_save: If True, use no-memory-save variant of dispatch header

    Returns:
        Message with dispatch header prepended
    """
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
